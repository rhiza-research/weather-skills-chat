<script lang="ts">
	import DOMPurify from 'dompurify';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { marked, type Token } from 'marked';
	import { unescapeHtml } from '$lib/utils';

	import { WEBUI_BASE_URL } from '$lib/constants';

	import CodeBlock from '$lib/components/chat/Messages/CodeBlock.svelte';
	import MarkdownInlineTokens from '$lib/components/chat/Messages/Markdown/MarkdownInlineTokens.svelte';
	import KatexRenderer from './KatexRenderer.svelte';
	import AlertRenderer, { alertComponent } from './AlertRenderer.svelte';
	import Collapsible from '$lib/components/common/Collapsible.svelte';
	import ActivityLine from '$lib/components/chat/Messages/ActivityLine.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { decodeEntities } from '$lib/utils/entities';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';

	import Source from './Source.svelte';
	import { settings } from '$lib/stores';

	const dispatch = createEventDispatcher();

	export let id: string;
	export let tokens: Token[];
	export let top = true;
	export let attributes = {};

	export let save = false;
	export let groupActivity = false;
	export let status = null;

	export let onTaskClick: Function = () => {};
	export let onSourceClick: Function = () => {};

	const ACTIVITY_TYPES = new Set(['reasoning', 'tool_calls', 'code_interpreter']);

	const isActivityDetails = (token: any) =>
		token?.type === 'details' && ACTIVITY_TYPES.has(token?.attributes?.type);

	const isPadding = (token: any) =>
		token?.type === 'space' ||
		((token?.type === 'paragraph' || token?.type === 'text' || token?.type === 'html') &&
			!String(token.text ?? token.raw ?? '').trim());

	const groupActivityTokens = (list: any[]) => {
		const out: any[] = [];
		let batch: any[] = [];
		const flush = () => {
			if (!batch.length) return;
			out.push({ type: 'activity_group', items: batch, raw: '' });
			batch = [];
		};
		for (const token of list ?? []) {
			if (isActivityDetails(token)) batch.push(token);
			else if (batch.length && isPadding(token)) continue;
			else {
				flush();
				out.push(token);
			}
		}
		flush();
		return out;
	};

	const unwrapJSON = (value: any): any => {
		if (typeof value !== 'string') return value;
		const trimmed = value.trim();
		if (!trimmed) return value;
		try {
			return unwrapJSON(JSON.parse(trimmed));
		} catch {
			return value;
		}
	};

	const toolFailed = (item: any) => {
		const parsed = unwrapJSON(decodeEntities(item?.attributes?.result ?? ''));
		if (!parsed || typeof parsed !== 'object') return false;
		if (parsed.ok === false) return true;
		return parsed.exit_code !== undefined && parsed.exit_code !== null && parsed.exit_code !== 0;
	};

	const hasDataImage = (item: any) => {
		const files = unwrapJSON(decodeEntities(item?.attributes?.files ?? ''));
		return Array.isArray(files) && files.some((file) => typeof file === 'string' && file.startsWith('data:image/'));
	};

	const isTranscriptOutput = (item: any) => {
		if (item?.attributes?.done !== 'true' || toolFailed(item)) return false;
		const type = item?.attributes?.type;
		const name = item?.attributes?.name;
		if (type === 'code_interpreter') return true;
		if (type === 'tool_calls' && (name === 'display_image' || name === 'execute_code')) return true;
		return type === 'tool_calls' && hasDataImage(item);
	};

	const inActivityDropdown = (item: any) => {
		const type = item?.attributes?.type;
		const name = item?.attributes?.name;
		if (type === 'code_interpreter') return false;
		if (name === 'execute_code') return false;
		return true;
	};

	$: displayTokens = (groupActivity ? groupActivityTokens(tokens) : tokens) as any[];
	$: lastActivityIdx = (() => {
		let idx = -1;
		for (let i = 0; i < displayTokens.length; i++) {
			if (displayTokens[i]?.type === 'activity_group') idx = i;
		}
		return idx;
	})();

	const headerComponent = (depth: number) => {
		return 'h' + depth;
	};

	const tokenKey = (token: Token, tokenIdx: number) => {
		const attrs = (token as any)?.attributes;
		if ((token as any)?.type === 'activity_group') {
			return `activity-${tokenIdx}`;
		}
		if (token?.type === 'details' && attrs?.id) {
			return `details-${attrs.id}`;
		}
		if (token?.type === 'details' && attrs?.type && attrs?.name) {
			return `details-${attrs.type}-${attrs.name}-${tokenIdx}`;
		}
		return tokenIdx;
	};

	const exportTableToCSVHandler = (token, tokenIdx = 0) => {
		console.log('Exporting table to CSV');

		// Extract header row text and escape for CSV.
		const header = token.header.map((headerCell) => `"${headerCell.text.replace(/"/g, '""')}"`);

		// Create an array for rows that will hold the mapped cell text.
		const rows = token.rows.map((row) =>
			row.map((cell) => {
				// Map tokens into a single text
				const cellContent = cell.tokens.map((token) => token.text).join('');
				// Escape double quotes and wrap the content in double quotes
				return `"${cellContent.replace(/"/g, '""')}"`;
			})
		);

		// Combine header and rows
		const csvData = [header, ...rows];

		// Join the rows using commas (,) as the separator and rows using newline (\n).
		const csvContent = csvData.map((row) => row.join(',')).join('\n');

		// Log rows and CSV content to ensure everything is correct.
		console.log(csvData);
		console.log(csvContent);

		// To handle Unicode characters, you need to prefix the data with a BOM:
		const bom = '\uFEFF'; // BOM for UTF-8

		// Create a new Blob prefixed with the BOM to ensure proper Unicode encoding.
		const blob = new Blob([bom + csvContent], { type: 'text/csv;charset=UTF-8' });

		// Use FileSaver.js's saveAs function to save the generated CSV file.
		saveAs(blob, `table-${id}-${tokenIdx}.csv`);
	};
</script>

<!-- {JSON.stringify(tokens)} -->
{#each displayTokens as token, tokenIdx (tokenKey(token, tokenIdx))}
	{#if token.type === 'hr'}
		<hr class=" border-gray-100 dark:border-gray-850" />
	{:else if token.type === 'heading'}
		<svelte:element this={headerComponent(token.depth)} dir="auto">
			<MarkdownInlineTokens id={`${id}-${tokenIdx}-h`} tokens={token.tokens} {onSourceClick} />
		</svelte:element>
	{:else if token.type === 'code'}
		{#if token.raw.includes('```')}
			<CodeBlock
				id={`${id}-${tokenIdx}`}
				collapsed={$settings?.collapseCodeBlocks ?? false}
				{token}
				lang={token?.lang ?? ''}
				code={token?.text ?? ''}
				{attributes}
				{save}
				onCode={(value) => {
					dispatch('code', value);
				}}
				onSave={(value) => {
					dispatch('update', {
						raw: token.raw,
						oldContent: token.text,
						newContent: value
					});
				}}
			/>
		{:else}
			{token.text}
		{/if}
	{:else if token.type === 'table'}
		<div class="relative w-full group">
			<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-lg">
				<table
					class=" w-full text-sm text-left text-gray-500 dark:text-gray-400 max-w-full rounded-xl"
				>
					<thead
						class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 border-none"
					>
						<tr class="">
							{#each token.header as header, headerIdx}
								<th
									scope="col"
									class="px-3! py-1.5! cursor-pointer border border-gray-100 dark:border-gray-850"
									style={token.align[headerIdx] ? '' : `text-align: ${token.align[headerIdx]}`}
								>
									<div class="gap-1.5 text-left">
										<div class="shrink-0 break-normal">
											<MarkdownInlineTokens
												id={`${id}-${tokenIdx}-header-${headerIdx}`}
												tokens={header.tokens}
												{onSourceClick}
											/>
										</div>
									</div>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each token.rows as row, rowIdx}
							<tr class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs">
								{#each row ?? [] as cell, cellIdx}
									<td
										class="px-3! py-1.5! text-gray-900 dark:text-white w-max border border-gray-100 dark:border-gray-850"
										style={token.align[cellIdx] ? '' : `text-align: ${token.align[cellIdx]}`}
									>
										<div class="break-normal">
											<MarkdownInlineTokens
												id={`${id}-${tokenIdx}-row-${rowIdx}-${cellIdx}`}
												tokens={cell.tokens}
												{onSourceClick}
											/>
										</div>
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<div class=" absolute top-1 right-1.5 z-20 invisible group-hover:visible">
				<Tooltip content={$i18n.t('Export to CSV')}>
					<button
						class="p-1 rounded-lg bg-transparent transition"
						on:click={(e) => {
							e.stopPropagation();
							exportTableToCSVHandler(token, tokenIdx);
						}}
					>
						<ArrowDownTray className=" size-3.5" strokeWidth="1.5" />
					</button>
				</Tooltip>
			</div>
		</div>
	{:else if token.type === 'blockquote'}
		{@const alert = alertComponent(token)}
		{#if alert}
			<AlertRenderer {token} {alert} />
		{:else}
			<blockquote dir="auto">
				<svelte:self id={`${id}-${tokenIdx}`} tokens={token.tokens} {onTaskClick} {onSourceClick} />
			</blockquote>
		{/if}
	{:else if token.type === 'list'}
		{#if token.ordered}
			<ol start={token.start || 1} dir="auto">
				{#each token.items as item, itemIdx}
					<li class="text-start">
						{#if item?.task}
							<input
								class=" translate-y-[1px] -translate-x-1"
								type="checkbox"
								checked={item.checked}
								on:change={(e) => {
									onTaskClick({
										id: id,
										token: token,
										tokenIdx: tokenIdx,
										item: item,
										itemIdx: itemIdx,
										checked: e.target.checked
									});
								}}
							/>
						{/if}

						<svelte:self
							id={`${id}-${tokenIdx}-${itemIdx}`}
							tokens={item.tokens}
							top={token.loose}
							{onTaskClick}
							{onSourceClick}
						/>
					</li>
				{/each}
			</ol>
		{:else}
			<ul dir="auto">
				{#each token.items as item, itemIdx}
					<li class="text-start">
						{#if item?.task}
							<input
								class=" translate-y-[1px] -translate-x-1"
								type="checkbox"
								checked={item.checked}
								on:change={(e) => {
									onTaskClick({
										id: id,
										token: token,
										tokenIdx: tokenIdx,
										item: item,
										itemIdx: itemIdx,
										checked: e.target.checked
									});
								}}
							/>
						{/if}

						<svelte:self
							id={`${id}-${tokenIdx}-${itemIdx}`}
							tokens={item.tokens}
							top={token.loose}
							{onTaskClick}
							{onSourceClick}
						/>
					</li>
				{/each}
			</ul>
		{/if}
	{:else if token.type === 'activity_group'}
		<ActivityLine items={token.items} status={tokenIdx === lastActivityIdx ? status : null}>
			{#each token.items as item, itemIdx}
				{#if inActivityDropdown(item)}
					<Collapsible
						title={item.summary}
						open={$settings?.expandDetails ?? false}
						attributes={item?.attributes}
						showResultMedia={false}
						className="w-full space-y-1"
						dir="auto"
					>
						<div class="mb-1.5" slot="content">
							<svelte:self
								id={`${id}-${tokenIdx}-${itemIdx}-d`}
								tokens={marked.lexer(item.text ?? '')}
								attributes={item?.attributes}
								{onTaskClick}
								{onSourceClick}
							/>
						</div>
					</Collapsible>
				{/if}
			{/each}
		</ActivityLine>
		{#each token.items as item, itemIdx}
			{#if isTranscriptOutput(item)}
				<Collapsible
					title={item.summary}
					open={item?.attributes?.name === 'execute_code' ||
						item?.attributes?.type === 'code_interpreter'}
					attributes={item?.attributes}
					showTitle={item?.attributes?.name !== 'display_image' && !hasDataImage(item)}
					className="w-full space-y-1"
					dir="auto"
				>
					<div class="mb-1.5" slot="content">
						<svelte:self
							id={`${id}-${tokenIdx}-${itemIdx}-out`}
							tokens={marked.lexer(item.text ?? '')}
							attributes={item?.attributes}
							{onTaskClick}
							{onSourceClick}
						/>
					</div>
				</Collapsible>
			{/if}
		{/each}
	{:else if token.type === 'details'}
		<Collapsible
			title={token.summary}
			open={token?.attributes?.name === 'execute_code' ? true : ($settings?.expandDetails ?? false)}
			attributes={token?.attributes}
			className="w-full space-y-1"
			dir="auto"
		>
			<div class=" mb-1.5" slot="content">
				<svelte:self
					id={`${id}-${tokenIdx}-d`}
					tokens={marked.lexer(token.text)}
					attributes={token?.attributes}
					{onTaskClick}
					{onSourceClick}
				/>
			</div>
		</Collapsible>
	{:else if token.type === 'html'}
		{@const html = DOMPurify.sanitize(token.text)}
		{#if html && html.includes('<video')}
			{@html html}
		{:else if token.text.includes(`<iframe src="${WEBUI_BASE_URL}/api/v1/files/`)}
			{@html `${token.text}`}
		{:else if token.text.includes(`<source_id`)}
			<Source {id} {token} onClick={onSourceClick} />
		{:else}
			{token.text}
		{/if}
	{:else if token.type === 'iframe'}
		<iframe
			src="{WEBUI_BASE_URL}/api/v1/files/{token.fileId}/content"
			title={token.fileId}
			width="100%"
			frameborder="0"
			onload="this.style.height=(this.contentWindow.document.body.scrollHeight+20)+'px';"
		></iframe>
	{:else if token.type === 'paragraph'}
		<p dir="auto">
			<MarkdownInlineTokens
				id={`${id}-${tokenIdx}-p`}
				tokens={token.tokens ?? []}
				{onSourceClick}
			/>
		</p>
	{:else if token.type === 'text'}
		{#if top}
			<p>
				{#if token.tokens}
					<MarkdownInlineTokens id={`${id}-${tokenIdx}-t`} tokens={token.tokens} {onSourceClick} />
				{:else}
					{unescapeHtml(token.text)}
				{/if}
			</p>
		{:else if token.tokens}
			<MarkdownInlineTokens
				id={`${id}-${tokenIdx}-p`}
				tokens={token.tokens ?? []}
				{onSourceClick}
			/>
		{:else}
			{unescapeHtml(token.text)}
		{/if}
	{:else if token.type === 'inlineKatex'}
		{#if token.text}
			<KatexRenderer content={token.text} displayMode={token?.displayMode ?? false} />
		{/if}
	{:else if token.type === 'blockKatex'}
		{#if token.text}
			<KatexRenderer content={token.text} displayMode={token?.displayMode ?? false} />
		{/if}
	{:else if token.type === 'space'}
		<div class="my-2" />
	{:else}
		{console.log('Unknown token', token)}
	{/if}
{/each}
