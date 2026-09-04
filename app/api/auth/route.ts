import {
  authConfigured, clearSessionCookie, createSessionCookie, isAuthenticated, verifyLoginPassword,
} from '@/lib/auth';

export const runtime = 'edge';

export async function GET(request: Request) {
  return Response.json({ authenticated: await isAuthenticated(request), configured: authConfigured() });
}

export async function POST(request: Request) {
  if (!authConfigured()) return Response.json({ error: '所有者登录尚未配置。' }, { status: 503 });
  const body = await request.json().catch(() => null) as { password?: unknown } | null;
  const password = typeof body?.password === 'string' ? body.password : '';
  if (!(await verifyLoginPassword(password))) {
    return Response.json({ error: '密码不正确。' }, { status: 401 });
  }
  return Response.json(
    { authenticated: true },
    { headers: { 'Set-Cookie': await createSessionCookie(request), 'Cache-Control': 'no-store' } },
  );
}

export async function DELETE(request: Request) {
  return Response.json(
    { authenticated: false },
    { headers: { 'Set-Cookie': clearSessionCookie(request), 'Cache-Control': 'no-store' } },
  );
}
