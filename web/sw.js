/* 拼好卷 · Service Worker
 * 目标：断网/弱网下仍能打开页面、翻看已加载过的卷子。
 * 策略：
 *   - 预缓存：外壳（HTML/CSS/JS/本地 KaTeX/marked/图标）
 *   - 同源静态资源：stale-while-revalidate（先给缓存，再后台更新）
 *   - /api/*：network-first（保证数据新鲜），断网时回退到上一次的缓存
 *   - 跨域 CDN（KaTeX/marked 回退源）：cache-first，避免每次回源
 * 注意：只处理 GET；POST（判分/导入等）一律直连，不缓存。
 */
const VERSION = 'kpp-v1';
const PRECACHE = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './manifest.webmanifest',
  './icon.svg',
  '/assets/katex/katex.min.css',
  '/assets/katex/katex.min.js',
  '/assets/katex/auto-render.min.js',
  '/assets/vendor/marked.min.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION)
      // 单个资源 404 不应该让整次安装失败，故逐个 add 并吞掉失败
      .then((cache) => Promise.all(PRECACHE.map((u) => cache.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  const isApi = url.pathname.startsWith('/api/');
  const isSameOrigin = url.origin === self.location.origin;

  // API：网络优先，断网回退缓存
  if (isApi) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || Response.error()))
    );
    return;
  }

  if (!isSameOrigin) {
    // CDN 回退源：缓存优先（本地资源缺失时才用到，缓存住可离线复用）
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => hit))
    );
    return;
  }

  // 同源静态资源：stale-while-revalidate
  event.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req).then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
