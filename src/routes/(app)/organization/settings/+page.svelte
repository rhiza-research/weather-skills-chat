<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getOrganizationById, updateOrganizationById } from '$lib/apis/organizations';
	import { activeOrganizationId, organizations } from '$lib/stores';

	const i18n = getContext('i18n');

	let name = '';
	let logo = '';
	let loadedId = '';
	let saving = false;
	let fileInput: HTMLInputElement;

	const load = async (id: string) => {
		if (!id || id === loadedId) {
			return;
		}
		try {
			const org = await getOrganizationById(localStorage.token, id);
			name = org?.name ?? '';
			logo = org?.logo ?? '';
			loadedId = id;
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	$: if ($activeOrganizationId) {
		load($activeOrganizationId);
	}

	const cropLogo = (file: File) => {
		const reader = new FileReader();
		reader.onload = (event) => {
			const img = new Image();
			img.src = `${event.target?.result ?? ''}`;
			img.onload = () => {
				const canvas = document.createElement('canvas');
				const ctx = canvas.getContext('2d');
				if (!ctx) {
					return;
				}
				const aspectRatio = img.width / img.height;
				let newWidth;
				let newHeight;
				if (aspectRatio > 1) {
					newWidth = 250 * aspectRatio;
					newHeight = 250;
				} else {
					newWidth = 250;
					newHeight = 250 / aspectRatio;
				}
				canvas.width = 250;
				canvas.height = 250;
				ctx.drawImage(img, (250 - newWidth) / 2, (250 - newHeight) / 2, newWidth, newHeight);
				logo = canvas.toDataURL('image/jpeg');
				fileInput.value = '';
			};
		};
		reader.readAsDataURL(file);
	};

	const onLogo = (event: Event) => {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) {
			return;
		}
		if (!['image/gif', 'image/webp', 'image/jpeg', 'image/png'].includes(file.type)) {
			toast.error($i18n.t('File type not supported.'));
			input.value = '';
			return;
		}
		cropLogo(file);
	};

	const save = async () => {
		const id = $activeOrganizationId;
		if (!id || !name.trim()) {
			toast.error($i18n.t('Organization name cannot be empty.'));
			return;
		}
		saving = true;
		try {
			const updated = await updateOrganizationById(localStorage.token, id, {
				name: name.trim(),
				logo: logo || ''
			});
			organizations.update((list) =>
				(list ?? []).map((item) => (item.id === updated.id ? { ...item, ...updated } : item))
			);
			name = updated.name ?? name;
			logo = updated.logo ?? '';
			toast.success($i18n.t('Organization updated.'));
		} catch (error) {
			toast.error(`${error}`);
		}
		saving = false;
	};
</script>

<div class="mt-0.5 mb-3 flex flex-col gap-1">
	<div class="text-lg font-medium px-0.5">{$i18n.t('Organization settings')}</div>
</div>

<div class="max-w-xl flex flex-col gap-4 text-sm">
	<div class="flex flex-col gap-1">
		<div class="text-xs font-medium text-gray-500">{$i18n.t('Name')}</div>
		<input
			class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
			bind:value={name}
		/>
	</div>

	<div class="flex flex-col gap-2">
		<div class="text-xs font-medium text-gray-500">{$i18n.t('Logo')}</div>
		<div class="flex items-center gap-4">
			{#if logo}
				<img src={logo} alt="" class="size-16 rounded-full object-cover bg-gray-100 dark:bg-gray-850" />
			{:else}
				<div
					class="size-16 rounded-full bg-gray-100 dark:bg-gray-850 flex items-center justify-center text-xs text-gray-400"
				>
					{$i18n.t('None')}
				</div>
			{/if}
			<div class="flex flex-col gap-2">
				<input bind:this={fileInput} type="file" accept="image/*" hidden on:change={onLogo} />
				<button
					class="px-3 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition font-medium"
					type="button"
					on:click={() => fileInput.click()}
				>
					{$i18n.t('Upload logo')}
				</button>
				{#if logo}
					<button
						class="self-start text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
						type="button"
						on:click={() => {
							logo = '';
						}}
					>
						{$i18n.t('Remove logo')}
					</button>
				{/if}
			</div>
		</div>
	</div>

	<div>
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
			type="button"
			disabled={saving}
			on:click={save}
		>
			{$i18n.t('Save')}
		</button>
	</div>
</div>
