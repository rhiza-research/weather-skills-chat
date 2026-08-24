<script lang="ts">
	import { decode } from 'html-entities';
	import { v4 as uuidv4 } from 'uuid';

	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	const i18n = getContext('i18n');

	import dayjs from '$lib/dayjs';
	import duration from 'dayjs/plugin/duration';
	import relativeTime from 'dayjs/plugin/relativeTime';

	dayjs.extend(duration);
	dayjs.extend(relativeTime);

	async function loadLocale(locales) {
		for (const locale of locales) {
			try {
				dayjs.locale(locale);
				break; // Stop after successfully loading the first available locale
			} catch (error) {
				console.error(`Could not load locale '${locale}':`, error);
			}
		}
	}

	// Assuming $i18n.languages is an array of language codes
	$: loadLocale($i18n.languages);

	const dispatch = createEventDispatcher();

	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	import ChevronUp from '../icons/ChevronUp.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import Spinner from './Spinner.svelte';
	import Image from './Image.svelte';
	import ToolCallDetails from './ToolCallDetails.svelte';
	import { getArtifactContentUrl } from '$lib/apis/artifacts';
	import { chatId } from '$lib/stores';

	export let open = false;

	export let className = '';
	export let buttonClassName =
		'w-fit text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition';

	export let id = '';
	export let title = null;
	export let attributes = null;

	export let chevron = false;
	export let grow = false;

	export let disabled = false;
	export let hide = false;

	const collapsibleId = uuidv4();

	// Keep user-expanded state across parent re-renders (e.g. streaming content updates).
	let userControlled = false;
	let localOpen = open;
	$: if (!userControlled) {
		localOpen = open;
	}
	$: dispatch('change', localOpen);

	const toggleOpen = () => {
		if (disabled) return;
		userControlled = true;
		localOpen = !localOpen;
		open = localOpen;
	};

	function unwrapJSON(value: any): any {
		if (typeof value !== 'string') {
			return value;
		}
		const trimmed = value.trim();
		if (!trimmed) {
			return value;
		}
		try {
			return unwrapJSON(JSON.parse(trimmed));
		} catch (e) {
			return value;
		}
	}

	function formatArgValue(value: any): string {
		if (value === null || value === undefined) {
			return 'null';
		}
		if (typeof value === 'string') {
			if (value === '') {
				return '""';
			}
			if (/[\s"'\\]/.test(value)) {
				return JSON.stringify(value);
			}
			return value;
		}
		if (typeof value === 'number' || typeof value === 'boolean') {
			return String(value);
		}
		try {
			return JSON.stringify(value);
		} catch (e) {
			return String(value);
		}
	}

	function formatToolCallSignature(name: string, argsRaw: string): string {
		const toolName = name || 'tool';
		const args = unwrapJSON(argsRaw);

		if (args && typeof args === 'object' && !Array.isArray(args) && Array.isArray(args.argv)) {
			const parts = [toolName];
			if (args.script) {
				parts.push(formatArgValue(args.script));
			}
			for (const arg of args.argv) {
				parts.push(formatArgValue(arg));
			}
			return parts.join(' ');
		}

		if (Array.isArray(args)) {
			if (args.length === 0) {
				return `${toolName}()`;
			}
			return [toolName, ...args.map(formatArgValue)].join(' ');
		}

		if (args && typeof args === 'object') {
			const entries = Object.entries(args);
			if (entries.length === 0) {
				return `${toolName}()`;
			}
			const inner = entries.map(([key, value]) => `${key}=${formatArgValue(value)}`).join(', ');
			return `${toolName}(${inner})`;
		}

		if (args === null || args === undefined || args === '') {
			return `${toolName}()`;
		}

		return `${toolName}(${formatArgValue(args)})`;
	}

	function parseLegacySkillOutput(text: string) {
		const sections: { stdout?: string; stderr?: string; meta: string[] } = { meta: [] };
		const lines = text.split(/\r?\n/);
		let mode: 'meta' | 'stdout' | 'stderr' = 'meta';
		const buckets = { stdout: [] as string[], stderr: [] as string[] };

		for (const line of lines) {
			if (/^stdout:\s*$/i.test(line)) {
				mode = 'stdout';
				continue;
			}
			if (/^stderr:\s*$/i.test(line)) {
				mode = 'stderr';
				continue;
			}
			if (mode === 'stdout') {
				buckets.stdout.push(line);
			} else if (mode === 'stderr') {
				buckets.stderr.push(line);
			} else if (line.trim()) {
				sections.meta.push(line);
			}
		}

		const stdout = buckets.stdout.join('\n').trim();
		const stderr = buckets.stderr.join('\n').trim();
		if (!stdout && !stderr) {
			return null;
		}

		const meta: Record<string, any> = {};
		for (const line of sections.meta) {
			const match = line.match(/^([a-zA-Z_]+)=(.*)$/);
			if (match) {
				meta[match[1]] = match[2];
			}
		}

		return {
			exit_code: meta.exit_code !== undefined ? Number(meta.exit_code) : undefined,
			script: meta.script,
			cwd: meta.cwd,
			stdout,
			stderr
		};
	}

	function parseToolResult(raw: string) {
		const parsed = unwrapJSON(raw);
		if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
			const hasStreams =
				'stdout' in parsed || 'stderr' in parsed || 'exit_code' in parsed || 'ok' in parsed;
			if (hasStreams) {
				return {
					kind: 'structured' as const,
					exit_code: parsed.exit_code,
					ok: parsed.ok,
					script: parsed.script,
					cwd: parsed.cwd,
					stdout: typeof parsed.stdout === 'string' ? parsed.stdout : '',
					stderr: typeof parsed.stderr === 'string' ? parsed.stderr : '',
					extra: parsed
				};
			}
		}

		if (typeof parsed === 'string') {
			const legacy = parseLegacySkillOutput(parsed);
			if (legacy) {
				return {
					kind: 'structured' as const,
					exit_code: legacy.exit_code,
					ok: legacy.exit_code === 0,
					script: legacy.script,
					cwd: legacy.cwd,
					stdout: legacy.stdout || '',
					stderr: legacy.stderr || '',
					extra: null
				};
			}
			return { kind: 'text' as const, text: parsed };
		}

		if (parsed === null || parsed === undefined || parsed === '') {
			return { kind: 'empty' as const };
		}

		return {
			kind: 'json' as const,
			text: typeof parsed === 'string' ? parsed : JSON.stringify(parsed, null, 2)
		};
	}

	function extractExecuteCodeSource(name: string, argsRaw: string): string | null {
		if (name !== 'execute_code') {
			return null;
		}
		const args = unwrapJSON(argsRaw);
		if (args && typeof args === 'object' && typeof args.code === 'string') {
			return args.code;
		}
		return null;
	}

	$: toolArgsRaw = attributes?.type === 'tool_calls' ? decode(attributes?.arguments ?? '') : '';
	$: toolCallSignature =
		attributes?.type === 'tool_calls'
			? formatToolCallSignature(attributes?.name ?? '', toolArgsRaw)
			: '';
	$: executeCodeSource =
		attributes?.type === 'tool_calls'
			? extractExecuteCodeSource(attributes?.name ?? '', toolArgsRaw)
			: null;
	$: toolResultRaw = attributes?.type === 'tool_calls' ? decode(attributes?.result ?? '') : '';
	$: toolResult = attributes?.type === 'tool_calls' ? parseToolResult(toolResultRaw) : null;
	$: toolFailed =
		toolResult?.kind === 'structured' &&
		((toolResult.exit_code !== undefined &&
			toolResult.exit_code !== null &&
			toolResult.exit_code !== 0) ||
			toolResult.ok === false);
	$: toolFiles =
		attributes?.type === 'tool_calls' ? unwrapJSON(decode(attributes?.files ?? '')) : null;

	$: displayImagePath = (() => {
		if (attributes?.type !== 'tool_calls' || attributes?.name !== 'display_image') {
			return null;
		}
		const args = unwrapJSON(toolArgsRaw);
		if (args && typeof args === 'object' && !Array.isArray(args)) {
			const path = typeof args.path === 'string' ? args.path.trim() : '';
			return path || null;
		}
		return null;
	})();

	let displayImageSrc = '';
	let displayImageLoadId = 0;

	async function loadDisplayImage(path: string, cid: string, loadId: number) {
		try {
			const res = await fetch(getArtifactContentUrl(cid, path), {
				headers: { authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) throw new Error(`artifact fetch failed: ${res.status}`);
			const blob = await res.blob();
			if (loadId !== displayImageLoadId) return;
			if (displayImageSrc.startsWith('blob:')) {
				URL.revokeObjectURL(displayImageSrc);
			}
			displayImageSrc = URL.createObjectURL(blob);
		} catch (err) {
			console.error('display_image load failed', err);
		}
	}

	$: if (displayImagePath && $chatId && attributes?.done === 'true') {
		displayImageLoadId += 1;
		loadDisplayImage(displayImagePath, $chatId, displayImageLoadId);
	} else if (displayImageSrc.startsWith('blob:')) {
		URL.revokeObjectURL(displayImageSrc);
		displayImageSrc = '';
	}

	onDestroy(() => {
		if (displayImageSrc.startsWith('blob:')) {
			URL.revokeObjectURL(displayImageSrc);
		}
	});

	const secretNamesFromValue = (value: any): string[] => {
		if (!Array.isArray(value)) return [];
		const names: string[] = [];
		const seen = new Set<string>();
		for (const item of value) {
			const name = typeof item === 'string' ? item.trim() : '';
			if (!name || seen.has(name)) continue;
			seen.add(name);
			names.push(name);
		}
		return names;
	};

	$: toolSecretNames = (() => {
		if (attributes?.type !== 'tool_calls') return [] as string[];
		const fromResult =
			toolResult?.kind === 'structured'
				? secretNamesFromValue(toolResult.extra?.env_secrets)
				: [];
		if (fromResult.length) return fromResult;
		const args = unwrapJSON(toolArgsRaw);
		if (args && typeof args === 'object' && !Array.isArray(args)) {
			return secretNamesFromValue(args.env_secrets);
		}
		return [] as string[];
	})();
</script>

<div {id} class={className}>
	{#if title !== null}
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<div
			class="{buttonClassName} cursor-pointer"
			on:pointerup={toggleOpen}
		>
			<div
				class=" w-full font-medium flex items-center justify-between gap-2 {attributes?.done &&
				attributes?.done !== 'true'
					? 'shimmer'
					: ''}
			"
			>
				{#if attributes?.done && attributes?.done !== 'true'}
					<div>
						<Spinner className="size-4" />
					</div>
				{/if}

				<div class="">
					{#if attributes?.type === 'reasoning'}
						{#if attributes?.done === 'true' && attributes?.duration}
							{#if attributes.duration < 60}
								{$i18n.t('Thought for {{DURATION}} seconds', {
									DURATION: attributes.duration
								})}
							{:else}
								{$i18n.t('Thought for {{DURATION}}', {
									DURATION: dayjs.duration(attributes.duration, 'seconds').humanize()
								})}
							{/if}
						{:else}
							{$i18n.t('Thinking...')}
						{/if}
					{:else if attributes?.type === 'code_interpreter'}
						{#if attributes?.done === 'true'}
							{$i18n.t('Analyzed')}
						{:else}
							{$i18n.t('Analyzing...')}
						{/if}
					{:else if attributes?.type === 'tool_calls'}
						<span class="text-sm font-medium text-gray-700 dark:text-gray-200">
							{#if attributes?.done === 'true'}
								{attributes.name}
								{#if toolFailed}
									<span class="ml-2 text-xs font-normal text-red-600 dark:text-red-400"
										>{$i18n.t('failed')}</span
									>
								{/if}
							{:else}
								{$i18n.t('Running')} {attributes.name}…
							{/if}
						</span>
					{:else}
						{title}
					{/if}
				</div>

				<div class="flex self-center translate-y-[1px]">
					{#if localOpen}
						<ChevronUp strokeWidth="3.5" className="size-3.5" />
					{:else}
						<ChevronDown strokeWidth="3.5" className="size-3.5" />
					{/if}
				</div>
			</div>
		</div>
	{:else}
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<div
			class="{buttonClassName} cursor-pointer"
			on:pointerup={toggleOpen}
		>
			<div>
				<div class="flex items-start justify-between">
					<slot />

					{#if chevron}
						<div class="flex self-start translate-y-1">
							{#if localOpen}
								<ChevronUp strokeWidth="3.5" className="size-3.5" />
							{:else}
								<ChevronDown strokeWidth="3.5" className="size-3.5" />
							{/if}
						</div>
					{/if}
				</div>

				{#if grow}
					{#if localOpen && !hide}
						<div
							transition:slide={{ duration: 300, easing: quintOut, axis: 'y' }}
							on:pointerup={(e) => {
								e.stopPropagation();
							}}
						>
							<slot name="content" />
						</div>
					{/if}
				{/if}
			</div>
		</div>
	{/if}

	{#if attributes?.type === 'tool_calls'}
		{#if !grow}
			{#if localOpen && !hide}
				<div
					class="mt-1.5 ml-1 border-l border-gray-200 pl-3 dark:border-gray-700"
					transition:slide={{ duration: 300, easing: quintOut, axis: 'y' }}
					on:pointerup={(e) => e.stopPropagation()}
				>
					<ToolCallDetails
						callSignature={toolCallSignature}
						pythonCode={executeCodeSource ?? ''}
						blockId={collapsibleId}
						done={attributes?.done === 'true'}
						result={toolResult}
						failed={toolFailed}
						secretNames={toolSecretNames}
					/>
				</div>
			{/if}

			{#if attributes?.done === 'true'}
				{#if displayImageSrc}
					<Image
						id={`${collapsibleId}-tool-calls-${attributes?.id}-display-image`}
						src={displayImageSrc}
						alt={displayImagePath ?? 'Image'}
					/>
				{:else if typeof toolFiles === 'object' && Array.isArray(toolFiles)}
					{#each toolFiles ?? [] as file, idx}
						{#if typeof file === 'string' && file.startsWith('data:image/')}
							<Image
								id={`${collapsibleId}-tool-calls-${attributes?.id}-result-${idx}`}
								src={file}
								alt="Image"
							/>
						{/if}
					{/each}
				{/if}
			{/if}
		{/if}
	{:else if !grow}
		{#if localOpen && !hide}
			<div transition:slide={{ duration: 300, easing: quintOut, axis: 'y' }}>
				<slot name="content" />
			</div>
		{/if}
	{/if}
</div>
