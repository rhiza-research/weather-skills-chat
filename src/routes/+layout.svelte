<script>
	import { spring } from 'svelte/motion';
	import { parseApiError } from '$lib/apis/response';

	let loadingProgress = spring(0, {
		stiffness: 0.05
	});

	import { onMount, tick, setContext } from 'svelte';
	import { get } from 'svelte/store';
	import {
		config,
		user,
		settings,
		theme,
		WEBUI_NAME,
		mobile,
		socket,
		chatId,
		chats,
		pinnedChats,
		tags,
		temporaryChatEnabled,
		isLastActiveTab,
		isApp,
		appInfo,
		artifactsRefresh,
		toolServers,
		preferencesReady
	} from '$lib/stores';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { Toaster, toast } from 'svelte-sonner';

	import { executeToolServer, getAppConfig, getUserConfig, mergeConfig } from '$lib/apis';
	import { getArtifactArchive, uploadArtifactArchive } from '$lib/apis/artifacts';
	import { getSessionUser } from '$lib/apis/auths';
	import { installOrganizationFetch } from '$lib/apis/organizations';

	installOrganizationFetch();

	import '../tailwind.css';
	import '../app.css';

	import { WEBUI_BASE_URL, WEBUI_HOSTNAME } from '$lib/constants';
	import i18n, { initI18n, getLanguages, changeLanguage } from '$lib/i18n';
	import { bestMatchingLanguage } from '$lib/utils';
	import { getAllTags } from '$lib/apis/chats';
	import { getTimeRange } from '$lib/utils';
	import {
		applyCachedStreamEvent,
		dropChat,
		onChatUpdated,
		rememberArtifacts,
		setOpenChat
	} from '$lib/chat/cache';
	import NotificationToast from '$lib/components/NotificationToast.svelte';
	import { requestChatTail } from '$lib/chat/scroll';
	import AppSidebar from '$lib/components/app/AppSidebar.svelte';
	import { chatCompletion } from '$lib/apis/openai';
	import { connectSocket } from '$lib/utils/socket';

	setContext('i18n', i18n);

	const bc = new BroadcastChannel('active-tab-channel');

	let loaded = false;

	const BREAKPOINT = 768;

	const serializePythonResult = (stdout, stderr, result, extra = {}) =>
		JSON.parse(
			JSON.stringify(
				{
					stdout: stdout,
					stderr: stderr,
					result: result,
					...extra
				},
				(_key, value) => (typeof value === 'bigint' ? value.toString() : value)
			)
		);

	const executePythonAsWorker = async (id, code, cb, options = {}) => {
		const { default: PyodideWorker } = await import('$lib/workers/pyodide.worker?worker');
		return new Promise((resolve) => {
			let result = null;
			let stdout = null;
			let stderr = null;
			let settled = false;

			const finish = (payload) => {
				if (settled) {
					return;
				}
				settled = true;
				if (cb) {
					cb(payload);
				}
				resolve(payload);
			};

			const packages = [
				code.includes('requests') ? 'requests' : null,
				code.includes('bs4') ? 'beautifulsoup4' : null,
				code.includes('numpy') ? 'numpy' : null,
				code.includes('pandas') ? 'pandas' : null,
				code.includes('matplotlib') ? 'matplotlib' : null,
				code.includes('sklearn') ? 'scikit-learn' : null,
				code.includes('scipy') ? 'scipy' : null,
				code.includes('re') ? 'regex' : null,
				code.includes('seaborn') ? 'seaborn' : null,
				code.includes('sympy') ? 'sympy' : null,
				code.includes('tiktoken') ? 'tiktoken' : null,
				code.includes('pytz') ? 'pytz' : null,
				code.includes('xarray') ? 'xarray' : null,
				code.includes('zarr') ? 'zarr' : null,
				code.includes('fsspec') ? 'fsspec' : null,
				code.includes('netCDF4') || code.includes('netcdf4') ? 'netcdf4' : null,
				code.includes('h5py') ? 'h5py' : null,
				code.includes('rasterio') ? 'rasterio' : null,
				code.includes('geopandas') ? 'geopandas' : null,
				code.includes('cartopy') ? 'cartopy' : null,
				code.includes('pyproj') ? 'pyproj' : null,
				code.includes('shapely') ? 'shapely' : null,
				code.includes('cftime') ? 'cftime' : null
			].filter(Boolean);

			const inputs = Array.isArray(options.inputs) ? options.inputs.filter(Boolean) : [];
			const outputs = Array.isArray(options.outputs) ? options.outputs.filter(Boolean) : [];
			const runChatId = options.chatId || '';

			const pyodideWorker = new PyodideWorker();

			setTimeout(() => {
				if (!settled) {
					stderr = 'Execution Time Limit Exceeded';
					pyodideWorker.terminate();
					finish(serializePythonResult(stdout, stderr, result));
				}
			}, 90000);

			const run = async () => {
				let inputArchive = null;
				try {
					if (inputs.length) {
						if (!runChatId || !localStorage.token) {
							throw new Error('Cannot copy artifact inputs without a saved chat session.');
						}
						inputArchive = await getArtifactArchive(localStorage.token, runChatId, inputs);
					}
				} catch (error) {
					pyodideWorker.terminate();
					const message = error?.detail || error?.message || String(error);
					finish(
						serializePythonResult(null, `Failed to copy inputs into Pyodide: ${message}`, null)
					);
					return;
				}

				pyodideWorker.onmessage = async (event) => {
					console.log('pyodideWorker.onmessage', event);
					const { id: _id, outputArchive, missingOutputs, ...data } = event.data;

					data['stdout'] && (stdout = data['stdout']);
					data['stderr'] && (stderr = data['stderr']);
					data['result'] && (result = data['result']);

					const extra = {};
					if (Array.isArray(missingOutputs) && missingOutputs.length) {
						extra.missing_outputs = missingOutputs;
					}

					if (outputArchive && runChatId && localStorage.token) {
						try {
							const uploaded = await uploadArtifactArchive(
								localStorage.token,
								runChatId,
								outputArchive
							);
							extra.copied_outputs = uploaded?.written || [];
							artifactsRefresh.update((n) => n + 1);
						} catch (error) {
							const message = error?.detail || error?.message || String(error);
							stderr = stderr
								? `${stderr}\nFailed to copy outputs into artifacts: ${message}`
								: `Failed to copy outputs into artifacts: ${message}`;
						}
					}

					finish(serializePythonResult(stdout, stderr, result, extra));
				};

				pyodideWorker.onerror = (event) => {
					console.log('pyodideWorker.onerror', event);
					finish(serializePythonResult(stdout, stderr, result));
				};

				const transfer = inputArchive ? [inputArchive] : [];
				pyodideWorker.postMessage(
					{
						id: id,
						code: code,
						packages: packages,
						inputArchive,
						outputs
					},
					transfer
				);
			};

			void run();
		});
	};

	const executeTool = async (data, cb) => {
		const toolServer = $settings?.toolServers?.find((server) => server.url === data.server?.url);
		const toolServerData = $toolServers?.find((server) => server.url === data.server?.url);

		console.log('executeTool', data, toolServer);

		let payload;
		if (toolServer) {
			console.log(toolServer);
			const res = await executeToolServer(
				(toolServer?.auth_type ?? 'bearer') === 'bearer' ? toolServer?.key : localStorage.token,
				toolServer.url,
				data?.name,
				data?.params,
				toolServerData
			);

			console.log('executeToolServer', res);
			payload = JSON.parse(JSON.stringify(res));
		} else {
			payload = JSON.parse(
				JSON.stringify({
					error: 'Tool Server Not Found'
				})
			);
		}
		if (cb) {
			cb(payload);
		}
		return payload;
	};

	const applyChatListRow = (row) => {
		if (!row?.id) return;
		if (row.removed || row.archived) {
			chats.update((list) => (list ?? []).filter((item) => item.id !== row.id));
			pinnedChats.update((list) => (list ?? []).filter((item) => item.id !== row.id));
			return;
		}
		const next = { ...row, time_range: getTimeRange(row.updated_at) };
		if (row.pinned) {
			chats.update((list) => (list ?? []).filter((item) => item.id !== row.id));
			pinnedChats.update((list) => {
				const items = [...(list ?? [])];
				const index = items.findIndex((item) => item.id === row.id);
				if (index === -1) items.unshift(next);
				else items[index] = { ...items[index], ...next };
				return items;
			});
			return;
		}
		pinnedChats.update((list) => (list ?? []).filter((item) => item.id !== row.id));
		chats.update((list) => {
			const items = [...(list ?? [])];
			const index = items.findIndex((item) => item.id === row.id);
			if (index === -1) items.unshift(next);
			else items[index] = { ...items[index], ...next };
			return items;
		});
	};

	$: setOpenChat($chatId || '');

	const chatEventHandler = async (event, cb) => {
		const chat = $page.url.pathname.includes(`/c/${event.chat_id}`);

		let isFocused = document.visibilityState !== 'visible';
		if (window.electronAPI) {
			const res = await window.electronAPI.send({
				type: 'window:isFocused'
			});
			if (res) {
				isFocused = res.isFocused;
			}
		}

		await tick();
		const type = event?.data?.type ?? null;
		const data = event?.data?.data ?? null;
		applyCachedStreamEvent(event, localStorage.token);

		if (type === 'chat:title') {
			const title = typeof data === 'string' ? data : data?.title;
			if (title && event.chat_id) {
				chats.update((list) =>
					(list ?? []).map((item) =>
						item.id === event.chat_id ? { ...item, title } : item
					)
				);
			}
		}

		// Session-targeted RPC (Pyodide, tool servers, direct completion) must always
		// run and ack. The backend sio.call blocks on this callback; gating on the
		// active chat or tab visibility leaves the interpreter loop without output.
		if (data?.session_id === $socket.id) {
			if (type === 'execute:python') {
				console.log('execute:python', data);
				return await executePythonAsWorker(data.id, data.code, cb, {
					chatId: data.chat_id,
					inputs: data.inputs,
					outputs: data.outputs
				});
			} else if (type === 'execute:tool') {
				console.log('execute:tool', data);
				return await executeTool(data, cb);
			} else if (type === 'request:chat:completion') {
				console.log(data, $socket.id);
				const { session_id, channel, form_data, model } = data;

				try {
					const directConnections = $settings?.directConnections ?? {};

					if (directConnections) {
						const urlIdx = model?.urlIdx;

						const OPENAI_API_URL = directConnections.OPENAI_API_BASE_URLS[urlIdx];
						const OPENAI_API_KEY = directConnections.OPENAI_API_KEYS[urlIdx];
						const API_CONFIG = directConnections.OPENAI_API_CONFIGS[urlIdx];

						try {
							if (API_CONFIG?.prefix_id) {
								const prefixId = API_CONFIG.prefix_id;
								form_data['model'] = form_data['model'].replace(`${prefixId}.`, ``);
							}

							const [res, controller] = await chatCompletion(
								OPENAI_API_KEY,
								form_data,
								OPENAI_API_URL
							);

							if (res) {
								// raise if the response is not ok
								if (!res.ok) {
									throw await parseApiError(res);
								}

								if (form_data?.stream ?? false) {
									cb({
										status: true
									});
									console.log({ status: true });

									// res will either be SSE or JSON
									const reader = res.body.getReader();
									const decoder = new TextDecoder();

									const processStream = async () => {
										while (true) {
											// Read data chunks from the response stream
											const { done, value } = await reader.read();
											if (done) {
												break;
											}

											// Decode the received chunk
											const chunk = decoder.decode(value, { stream: true });

											// Process lines within the chunk
											const lines = chunk.split('\n').filter((line) => line.trim() !== '');

											for (const line of lines) {
												console.log(line);
												$socket?.emit(channel, line);
											}
										}
									};

									// Process the stream in the background
									await processStream();
								} else {
									const data = await res.json();
									cb(data);
								}
							} else {
								throw new Error('An error occurred while fetching the completion');
							}
						} catch (error) {
							console.error('chatCompletion', error);
							cb(error);
						}
					}
				} catch (error) {
					console.error('chatCompletion', error);
					cb(error);
				} finally {
					$socket.emit(channel, {
						done: true
					});
				}
			} else {
				console.log('chatEventHandler', event);
			}
			return;
		}

		if ((event.chat_id !== $chatId && !$temporaryChatEnabled) || isFocused) {
			if (type === 'chat:completion') {
				const { done, content, title } = data;

				if (done) {
					if ($isLastActiveTab) {
						if ($settings?.notificationEnabled ?? false) {
							new Notification(`${title} | Weather Skills`, {
								body: content,
								icon: `${WEBUI_BASE_URL}/static/favicon.png`
							});
						}
					}

					toast.custom(NotificationToast, {
						componentProps: {
							onClick: () => {
								requestChatTail(event.chat_id);
								goto(`/c/${event.chat_id}`);
							},
							content: content,
							title: title
						},
						duration: 15000,
						unstyled: true
					});
				}
			} else if (type === 'chat:title') {
				// List refresh handled above.
			} else if (type === 'chat:tags') {
				tags.set(await getAllTags(localStorage.token));
			}
		}
	};

	onMount(async () => {
		if (typeof window !== 'undefined' && window.applyTheme) {
			window.applyTheme();
		}

		if (window?.electronAPI) {
			const info = await window.electronAPI.send({
				type: 'app:info'
			});

			if (info) {
				isApp.set(true);
				appInfo.set(info);

				const data = await window.electronAPI.send({
					type: 'app:data'
				});

				if (data) {
					appData.set(data);
				}
			}
		}

		// Listen for messages on the BroadcastChannel
		bc.onmessage = (event) => {
			if (event.data === 'active') {
				isLastActiveTab.set(false); // Another tab became active
			}
		};

		// Set yourself as the last active tab when this tab is focused
		const handleVisibilityChange = () => {
			if (document.visibilityState === 'visible') {
				isLastActiveTab.set(true); // This tab is now the active tab
				bc.postMessage('active'); // Notify other tabs that this tab is active
			}
		};

		// Add event listener for visibility state changes
		document.addEventListener('visibilitychange', handleVisibilityChange);

		// Call visibility change handler initially to set state on load
		handleVisibilityChange();

		theme.set(localStorage.theme);

		mobile.set(window.innerWidth < BREAKPOINT);

		const onResize = () => {
			if (window.innerWidth < BREAKPOINT) {
				mobile.set(true);
			} else {
				mobile.set(false);
			}
		};
		window.addEventListener('resize', onResize);

		const onChatList = (row) => applyChatListRow(row);
		const onChatUpdatedEvent = (row) => {
			if (!row?.id) return;
			onChatUpdated(row.id, Number(row.revision ?? 0), localStorage.token);
		};
		const onChatArtifacts = (row) => {
			if (!row?.id || !Array.isArray(row.files)) return;
			rememberArtifacts(row.id, row.files);
		};
		const onChatEvict = (row) => {
			if (!row?.id) return;
			dropChat(row.id);
			chats.update((list) => (list ?? []).filter((item) => item.id !== row.id));
		};
		const bindRealtime = () => {
			const liveSocket = get(socket);
			if (!liveSocket) return;
			liveSocket.off('chat-events', chatEventHandler);
			liveSocket.off('chat:list', onChatList);
			liveSocket.off('chat:updated', onChatUpdatedEvent);
			liveSocket.off('chat:artifacts', onChatArtifacts);
			liveSocket.off('chat:evict', onChatEvict);
			if (get(user)) {
				liveSocket.on('chat-events', chatEventHandler);
				liveSocket.on('chat:list', onChatList);
				liveSocket.on('chat:updated', onChatUpdatedEvent);
				liveSocket.on('chat:artifacts', onChatArtifacts);
				liveSocket.on('chat:evict', onChatEvict);
				setOpenChat(get(chatId));
			}
		};
		user.subscribe(() => bindRealtime());
		socket.subscribe(() => bindRealtime());

		initI18n(localStorage?.locale);

		const token = localStorage.token;
		const encodedUrl = encodeURIComponent(
			`${window.location.pathname}${window.location.search}`
		);
		const applyAppConfig = async (appConfig) => {
			if (!appConfig) return;
			config.update((current) => mergeConfig(current, appConfig));
			await WEBUI_NAME.set(appConfig.name);
			if (localStorage.locale) return;
			const languages = await getLanguages();
			const browserLanguages = navigator.languages
				? navigator.languages
				: [navigator.language || navigator.userLanguage];
			const lang = appConfig.default_locale
				? appConfig.default_locale
				: bestMatchingLanguage(languages, browserLanguages, 'en-US');
			changeLanguage(lang);
		};
		const appConfigPromise = getAppConfig()
			.then((appConfig) => applyAppConfig(appConfig).then(() => appConfig))
			.catch((error) => {
				console.error('Error loading app config:', error);
				return null;
			});

		if (token) {
			preferencesReady.set(false);
			const socketPromise = connectSocket();
			getUserConfig(token)
				.then((userConfig) => {
					if (userConfig) config.update((current) => mergeConfig(current, userConfig));
				})
				.catch((error) => {
					console.error(error);
				});
			getSessionUser(token)
				.catch((error) => {
					toast.error(`${error}`);
					return null;
				})
				.then(async (sessionUser) => {
					if (!sessionUser) {
						localStorage.removeItem('token');
						await goto(`/auth?redirect=${encodedUrl}`);
						return;
					}
					await user.set(sessionUser);
					try {
						const liveSocket = await socketPromise;
						liveSocket.emit('user-join', { auth: { token: sessionUser.token } });
					} catch (error) {
						console.error(error);
					}
				});
			appConfigPromise.then((appConfig) => {
				if (!appConfig) goto('/error');
			});
			loaded = true;
		} else {
			const appConfig = await appConfigPromise;
			if (!appConfig) {
				await goto('/error');
			} else {
				const path = $page.url.pathname;
				if (path !== '/auth' && !path.startsWith('/auth/')) {
					await goto(`/auth?redirect=${encodedUrl}`);
				}
			}
		}

		await tick();

		if (
			document.documentElement.classList.contains('her') &&
			document.getElementById('progress-bar')
		) {
			loadingProgress.subscribe((value) => {
				const progressBar = document.getElementById('progress-bar');

				if (progressBar) {
					progressBar.style.width = `${value}%`;
				}
			});

			await loadingProgress.set(100);

			document.getElementById('splash-screen')?.remove();

			const audio = new Audio(`/audio/greeting.mp3`);
			const playAudio = () => {
				audio.play();
				document.removeEventListener('click', playAudio);
			};

			document.addEventListener('click', playAudio);

			loaded = true;
		} else {
			document.getElementById('splash-screen')?.remove();
			loaded = true;
		}

		return () => {
			window.removeEventListener('resize', onResize);
		};
	});
</script>

<svelte:head>
	<title>{$WEBUI_NAME}</title>

	<!-- rosepine themes have been disabled as it's not up to date with our latest version. -->
	<!-- feel free to make a PR to fix if anyone wants to see it return -->
	<!-- <link rel="stylesheet" type="text/css" href="/themes/rosepine.css" />
	<link rel="stylesheet" type="text/css" href="/themes/rosepine-dawn.css" /> -->
</svelte:head>

{#if loaded}
	{#if $isApp}
		<div class="flex flex-row h-screen">
			<AppSidebar />

			<div class="w-full flex-1 max-w-[calc(100%-4.5rem)]">
				<slot />
			</div>
		</div>
	{:else}
		<slot />
	{/if}
{/if}

<Toaster
	theme={$theme.includes('dark')
		? 'dark'
		: $theme === 'system'
			? window.matchMedia('(prefers-color-scheme: dark)').matches
				? 'dark'
				: 'light'
			: 'light'}
	richColors
	position="top-right"
/>
