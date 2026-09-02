<script>
	import { toast } from 'svelte-sonner';
	import { beforeNavigate, goto } from '$app/navigation';
	import { config, models, settings } from '$lib/stores';

	import { onMount, getContext } from 'svelte';
	import { createNewModel } from '$lib/apis/models';
	import { getModels } from '$lib/apis';

	import ModelEditor from '$lib/components/workspace/Models/ModelEditor.svelte';

	const i18n = getContext('i18n');

	const readCloneModel = () => {
		if (typeof sessionStorage === 'undefined' || !sessionStorage.model) {
			return null;
		}

		try {
			const parsed = JSON.parse(sessionStorage.model);
			sessionStorage.removeItem('model');
			const { user: _user, user_id, created_at, updated_at, ...rest } = parsed;
			return {
				...rest,
				access_control: rest.access_control ?? {}
			};
		} catch (error) {
			console.error(error);
			toast.error($i18n.t('Could not load model to clone'));
			return null;
		}
	};

	const onSubmit = async (modelInfo) => {
		if (($models ?? []).find((m) => m.id === modelInfo.id)) {
			toast.error(
				`Error: A model with the ID '${modelInfo.id}' already exists. Please select a different ID to proceed.`
			);
			return;
		}

		if (modelInfo.id === '') {
			toast.error('Error: Model ID cannot be empty. Please enter a valid ID to proceed.');
			return;
		}

		if (modelInfo) {
			const res = await createNewModel(localStorage.token, {
				...modelInfo,
				access_control: modelInfo.access_control ?? {},
				meta: {
					...modelInfo.meta,
					profile_image_url: modelInfo.meta.profile_image_url ?? '/static/favicon.png',
					suggestion_prompts: modelInfo.meta.suggestion_prompts
						? modelInfo.meta.suggestion_prompts.filter((prompt) => prompt.content !== '')
						: null
				},
				params: { ...modelInfo.params }
			}).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (res) {
				await models.set(
					await getModels(
						localStorage.token,
						$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
					)
				);
				toast.success($i18n.t('Model created successfully!'));
				await goto('/workspace/models');
			}
		}
	};

	let model = readCloneModel();

	// ModelEditor can leave SvelteKit's $page store out of sync with history on client nav.
	// Force a full load when leaving create so sidebar / workspace tabs always work.
	beforeNavigate(({ from, to, cancel }) => {
		if (!from?.url.pathname.includes('/workspace/models/create')) {
			return;
		}
		if (!to || from.url.pathname === to.url.pathname) {
			return;
		}
		cancel();
		window.location.assign(`${to.url.pathname}${to.url.search}${to.url.hash}`);
	});

	onMount(async () => {
		if ($models === null) {
			await models.set(
				await getModels(
					localStorage.token,
					$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
				)
			);
		}

		window.addEventListener('message', async (event) => {
			if (
				!['https://openwebui.com', 'https://www.openwebui.com', 'http://localhost:5173'].includes(
					event.origin
				)
			) {
				return;
			}

			let data = JSON.parse(event.data);

			if (data?.info) {
				data = data.info;
			}

			model = data;
		});

		if (window.opener ?? false) {
			window.opener.postMessage('loaded', '*');
		}
	});
</script>

<ModelEditor {model} {onSubmit} />
