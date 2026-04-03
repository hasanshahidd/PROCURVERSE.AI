import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

async function clearBrowserCaches() {
	try {
		if ("serviceWorker" in navigator) {
			const registrations = await navigator.serviceWorker.getRegistrations();
			await Promise.all(registrations.map((registration) => registration.unregister()));
		}

		if ("caches" in window) {
			const keys = await caches.keys();
			await Promise.all(keys.map((key) => caches.delete(key)));
		}
	} catch {
		// Ignore cache cleanup errors
	}
}

void clearBrowserCaches();

createRoot(document.getElementById("root")!).render(<App />);
