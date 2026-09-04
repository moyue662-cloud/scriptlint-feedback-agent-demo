const SESSION_COOKIE = 'sceneflow_session';
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7;

const encoder = new TextEncoder();

function secret(name: 'SCENEFLOW_LOGIN_PASSWORD' | 'SCENEFLOW_SESSION_SECRET') {
  const value = process.env[name]?.trim();
  return value || null;
}

async function sha256(value: string) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value)));
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

function toBase64Url(bytes: Uint8Array) {
  let binary = '';
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

async function signature(payload: string, sessionSecret: string) {
  const key = await crypto.subtle.importKey(
    'raw', encoder.encode(sessionSecret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  return toBase64Url(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(payload))));
}

function cookieValue(request: Request) {
  const cookieHeader = request.headers.get('cookie') ?? '';
  for (const item of cookieHeader.split(';')) {
    const [name, ...valueParts] = item.trim().split('=');
    if (name === SESSION_COOKIE) return valueParts.join('=');
  }
  return null;
}

export function authConfigured() {
  return Boolean(secret('SCENEFLOW_LOGIN_PASSWORD') && secret('SCENEFLOW_SESSION_SECRET'));
}

export async function verifyLoginPassword(candidate: string) {
  const expected = secret('SCENEFLOW_LOGIN_PASSWORD');
  if (!expected || !candidate) return false;
  return constantTimeEqual(await sha256(candidate), await sha256(expected));
}

export async function isAuthenticated(request: Request) {
  const sessionSecret = secret('SCENEFLOW_SESSION_SECRET');
  const session = cookieValue(request);
  if (!sessionSecret || !session) return false;
  const [version, expiresText, suppliedSignature] = session.split('.');
  if (version !== 'v1' || !expiresText || !suppliedSignature) return false;
  const expires = Number(expiresText);
  if (!Number.isFinite(expires) || expires <= Math.floor(Date.now() / 1000)) return false;
  const expectedSignature = await signature(`${version}.${expiresText}`, sessionSecret);
  return constantTimeEqual(encoder.encode(suppliedSignature), encoder.encode(expectedSignature));
}

export async function requireAuth(request: Request) {
  if (await isAuthenticated(request)) return null;
  return Response.json({ error: '请先登录后继续。' }, { status: 401 });
}

export async function createSessionCookie(request: Request) {
  const sessionSecret = secret('SCENEFLOW_SESSION_SECRET');
  if (!sessionSecret) throw new Error('登录会话尚未配置');
  const expires = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const payload = `v1.${expires}`;
  const value = `${payload}.${await signature(payload, sessionSecret)}`;
  const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : '';
  return `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${SESSION_TTL_SECONDS}${secure}`;
}

export function clearSessionCookie(request: Request) {
  const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : '';
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0${secure}`;
}
