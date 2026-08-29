import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: '剧序 SceneFlow｜短剧交互编译工作台',
  description: '将人类剧本转换为AI可稳定执行的交互节拍、规则报告与模型Prompt。',
  openGraph: {
    title: '剧序 SceneFlow｜短剧交互编译工作台',
    description: '把人类剧本，编译成 AI 能稳定执行的交互结构。',
    images: [{ url: '/og.png', width: 1792, height: 1024, alt: '剧序 SceneFlow' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '剧序 SceneFlow｜短剧交互编译工作台',
    description: '把人类剧本，编译成 AI 能稳定执行的交互结构。',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
