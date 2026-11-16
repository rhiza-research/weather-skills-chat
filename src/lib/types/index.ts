export type Banner = {
	id: string;
	type: string;
	title?: string;
	content: string;
	url?: string;
	timestamp: number;
	expires_at?: number | null;
};

export enum TTS_RESPONSE_SPLIT {
	PUNCTUATION = 'punctuation',
	PARAGRAPHS = 'paragraphs',
	NONE = 'none'
}
