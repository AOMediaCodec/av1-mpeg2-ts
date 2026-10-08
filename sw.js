// Service-worker kill-switch.
//
// The spec build ships its own sw.js. When the site was previously served
// with the spec at the ROOT, that worker registered at scope "/" and cached the
// old spec — which then masks this dashboard for anyone who visited before.
//
// This root worker exists only to UNDO that: on install it takes over, deletes
// all caches, unregisters itself, and reloads open clients so they fetch fresh
// content from the network. It intentionally caches nothing.
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Drop every cache this origin accumulated (old spec assets included).
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    // Remove ourselves so no worker controls this scope going forward.
    await self.registration.unregister();
    // Reload any open pages so they render the live dashboard, not a cache.
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach((client) => client.navigate(client.url));
  })());
});
