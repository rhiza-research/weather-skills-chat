// Appended by the artifact view route to HTML artifacts shown in the chat.
//
// Read only: this never changes the page. A Plotly figure saved at a fixed
// size (layout.width and layout.height) is drawn at that size, exactly as the
// skill made it; this tells the chat how big that is, including the page
// margin around it, and the chat scales the whole frame to fit, like an image.
// Responsive figures and other pages report nothing and fill the frame.
(function () {
	if (window.parent === window) return;
	var tries = 0;

	function report() {
		var gd = document.querySelector('.js-plotly-plot');
		if (!gd || !gd.layout) {
			if (++tries < 100) setTimeout(report, 100);
			return;
		}
		var width = Number(gd.layout.width);
		var height = Number(gd.layout.height);
		if (!(width > 0 && height > 0)) return;
		// The figure's box on the page, plus the same margin on the far side.
		var box = gd.getBoundingClientRect();
		var pageWidth = Math.ceil(box.right + Math.max(0, box.left));
		var pageHeight = Math.ceil(box.bottom + Math.max(0, box.top));
		window.parent.postMessage(
			{ type: 'weather-skills:figure-size', width: pageWidth, height: pageHeight },
			'*'
		);
	}

	if (document.readyState === 'complete') report();
	else window.addEventListener('load', report);
})();
