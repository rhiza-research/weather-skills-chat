import sha256 from 'js-sha256';

export const getGravatarURL = (email) => {
	const address = String(email).trim().toLowerCase();
	const hash = sha256(address);
	return `https://www.gravatar.com/avatar/${hash}`;
};
