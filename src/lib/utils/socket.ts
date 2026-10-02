import { get } from 'svelte/store';
import { activeUserIds, config, socket, USAGE_POOL } from '$lib/stores';
import { WEBUI_BASE_URL } from '$lib/constants';
import type { Socket } from 'socket.io-client';

let pending: Promise<Socket> | null = null;
let socketOpened = false;

/** Open the app socket once a session exists. Later calls reuse the same connection. */
export function connectSocket(): Promise<Socket> {
	const existing = get(socket);
	if (existing) {
		return Promise.resolve(existing);
	}
	if (!pending) {
		pending = openSocket().catch((error) => {
			pending = null;
			throw error;
		});
	}
	return pending;
}

async function openSocket(): Promise<Socket> {
	const { io } = await import('socket.io-client');
	const enableWebsocket = get(config)?.features?.enable_websocket ?? true;
	const liveSocket = io(`${WEBUI_BASE_URL}` || undefined, {
		reconnection: true,
		reconnectionDelay: 1000,
		reconnectionDelayMax: 5000,
		randomizationFactor: 0.5,
		path: '/ws/socket.io',
		transports: enableWebsocket ? ['websocket'] : ['polling', 'websocket'],
		auth: { token: localStorage.token }
	});

	liveSocket.on('connect_error', (err) => {
		console.log('connect_error', err);
	});

	liveSocket.on('connect', () => {
		console.log('connected', liveSocket.id);
		import('$lib/chat/cache').then(async (cache) => {
			const reconnect = socketOpened;
			socketOpened = true;
			cache.setSocketUp(true);
			cache.syncWatch(liveSocket);
			if (!localStorage.token) return;
			if (reconnect) await cache.refreshRecent(localStorage.token);
			await cache.refetchWatched(localStorage.token);
			cache.syncWatch(liveSocket);
		});
	});

	liveSocket.on('reconnect_attempt', (attempt) => {
		console.log('reconnect_attempt', attempt);
	});

	liveSocket.on('reconnect_failed', () => {
		console.log('reconnect_failed');
	});

	liveSocket.on('disconnect', (reason, details) => {
		import('$lib/chat/cache').then((cache) => cache.setSocketUp(false));
		console.log(`Socket ${liveSocket.id} disconnected due to ${reason}`);
		if (details) {
			console.log('Additional details:', details);
		}
	});

	liveSocket.on('user-list', (data) => {
		console.log('user-list', data);
		activeUserIds.set(data.user_ids);
	});

	liveSocket.on('usage', (data) => {
		console.log('usage', data);
		USAGE_POOL.set(data['models']);
	});

	socket.set(liveSocket);
	return liveSocket;
}
