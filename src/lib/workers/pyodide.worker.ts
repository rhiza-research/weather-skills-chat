import { loadPyodide, type PyodideInterface } from 'pyodide';

declare global {
	interface Window {
		stdout: string | null;
		stderr: string | null;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		result: any;
		pyodide: PyodideInterface;
		packages: string[];
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		[key: string]: any;
	}
}

async function loadPyodideAndPackages(packages: string[] = []) {
	self.stdout = null;
	self.stderr = null;
	self.result = null;

	self.pyodide = await loadPyodide({
		indexURL: '/pyodide/',
		stdout: (text) => {
			console.log('Python output:', text);

			if (self.stdout) {
				self.stdout += `${text}\n`;
			} else {
				self.stdout = `${text}\n`;
			}
		},
		stderr: (text) => {
			console.log('An error occurred:', text);
			if (self.stderr) {
				self.stderr += `${text}\n`;
			} else {
				self.stderr = `${text}\n`;
			}
		},
		packages: ['micropip']
	});

	let mountDir = '/mnt';
	self.pyodide.FS.mkdirTree(mountDir);
	// self.pyodide.FS.mount(self.pyodide.FS.filesystems.IDBFS, {}, mountDir);

	// // Load persisted files from IndexedDB (Initial Sync)
	// await new Promise<void>((resolve, reject) => {
	// 	self.pyodide.FS.syncfs(true, (err) => {
	// 		if (err) {
	// 			console.error('Error syncing from IndexedDB:', err);
	// 			reject(err);
	// 		} else {
	// 			console.log('Successfully loaded from IndexedDB.');
	// 			resolve();
	// 		}
	// 	});
	// });

	const micropip = self.pyodide.pyimport('micropip');

	// await micropip.set_index_urls('https://pypi.org/pypi/{package_name}/json');
	await micropip.install(packages);
}

self.onmessage = async (event) => {
	const { id, code, inputArchive, outputs, ...context } = event.data;

	console.log({ id, packages: context.packages, outputs, hasInputArchive: !!inputArchive });

	for (const key of Object.keys(context)) {
		self[key] = context[key];
	}

	await loadPyodideAndPackages(self.packages);

	try {
		await self.pyodide.loadPackagesFromImports(code);
	} catch (error) {
		console.error('loadPackagesFromImports failed:', error);
	}

	let outputArchive = null;
	let missingOutputs: string[] = [];

	try {
		self.pyodide.FS.mkdirTree('/mnt');
		self.pyodide.FS.mkdirTree('/tmp');

		if (inputArchive) {
			self.pyodide.FS.writeFile('/tmp/_inputs.tar.gz', new Uint8Array(inputArchive));
			await self.pyodide.runPythonAsync(`
import os, tarfile
os.makedirs('/mnt', exist_ok=True)
with tarfile.open('/tmp/_inputs.tar.gz', 'r:*') as tar:
    tar.extractall('/mnt', filter='data')
os.chdir('/mnt')
`);
		} else {
			await self.pyodide.runPythonAsync(`
import os
os.makedirs('/mnt', exist_ok=True)
os.chdir('/mnt')
`);
		}

		if (code.includes('matplotlib')) {
			await self.pyodide.runPythonAsync(`import base64
import os
from io import BytesIO

os.environ["MPLBACKEND"] = "AGG"

import matplotlib.pyplot

_old_show = matplotlib.pyplot.show
assert _old_show, "matplotlib.pyplot.show"

def show(*, block=None):
	buf = BytesIO()
	matplotlib.pyplot.savefig(buf, format="png")
	buf.seek(0)
	img_str = base64.b64encode(buf.read()).decode('utf-8')
	matplotlib.pyplot.clf()
	buf.close()
	print(f"data:image/png;base64,{img_str}")

matplotlib.pyplot.show = show`);
		}

		self.result = await self.pyodide.runPythonAsync(code);
		self.result = processResult(self.result);
		console.log('Python result:', self.result);
	} catch (error) {
		self.stderr = error.toString();
	}

	try {
		const outputPaths = Array.isArray(outputs) ? outputs : [];
		if (outputPaths.length) {
			self.pyodide.FS.writeFile('/tmp/_outputs.json', JSON.stringify(outputPaths));
			await self.pyodide.runPythonAsync(`
import json, os, tarfile, io
outs = json.load(open('/tmp/_outputs.json'))
missing = []
buf = io.BytesIO()
added = False
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    for rel in outs:
        rel = str(rel).replace('\\\\', '/').lstrip('/')
        if rel.startswith('mnt/'):
            rel = rel[4:]
        if not rel or '..' in rel.split('/'):
            missing.append(rel)
            continue
        src = os.path.join('/mnt', rel)
        if not os.path.exists(src):
            missing.append(rel)
            continue
        tar.add(src, arcname=rel)
        added = True
open('/tmp/_missing.json', 'w').write(json.dumps(missing))
open('/tmp/_out.tar.gz', 'wb').write(buf.getvalue() if added else b'')
`);
			const missingRaw = self.pyodide.FS.readFile('/tmp/_missing.json', { encoding: 'utf8' });
			missingOutputs = JSON.parse(missingRaw || '[]');
			const packed = self.pyodide.FS.readFile('/tmp/_out.tar.gz');
			if (packed && packed.byteLength > 0) {
				outputArchive = packed.buffer.slice(
					packed.byteOffset,
					packed.byteOffset + packed.byteLength
				);
			}
		}
	} catch (error) {
		const message = error?.toString?.() || String(error);
		self.stderr = self.stderr ? `${self.stderr}\n${message}` : message;
	}

	self.postMessage(
		{
			id,
			result: self.result,
			stdout: self.stdout,
			stderr: self.stderr,
			outputArchive,
			missingOutputs
		},
		outputArchive ? [outputArchive] : []
	);
};

function processResult(result: any): any {
	// Catch and always return JSON-safe string representations
	try {
		if (result == null) {
			// Handle null and undefined
			return null;
		}
		if (typeof result === 'string' || typeof result === 'number' || typeof result === 'boolean') {
			// Handle primitive types directly
			return result;
		}
		if (typeof result === 'bigint') {
			// Convert BigInt to a string for JSON-safe representation
			return result.toString();
		}
		if (Array.isArray(result)) {
			// If it's an array, recursively process items
			return result.map((item) => processResult(item));
		}
		if (typeof result.toJs === 'function') {
			// If it's a Pyodide proxy object (e.g., Pandas DF, Numpy Array), convert to JS and process recursively
			return processResult(result.toJs());
		}
		if (typeof result === 'object') {
			// Convert JS objects to a recursively serialized representation
			const processedObject: { [key: string]: any } = {};
			for (const key in result) {
				if (Object.prototype.hasOwnProperty.call(result, key)) {
					processedObject[key] = processResult(result[key]);
				}
			}
			return processedObject;
		}
		// Stringify anything that's left (e.g., Proxy objects that cannot be directly processed)
		return JSON.stringify(result);
	} catch (err) {
		// In case something unexpected happens, we return a stringified fallback
		return `[processResult error]: ${err.message || err.toString()}`;
	}
}

export default {};
