/** Credentials created by BOOTSTRAP_ADMIN_* on the empty test database. */
export const adminAccount = {
	email: process.env.E2E_ADMIN_EMAIL || 'admin@example.com',
	password: process.env.E2E_ADMIN_PASSWORD || 'password',
	name: process.env.E2E_ADMIN_NAME || 'Admin'
};
