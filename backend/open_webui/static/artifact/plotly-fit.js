// Appended by the artifact view route to HTML artifacts shown in the chat.
// Plotly figures are often saved at a fixed size (layout.width/height, and a
// wrapper div pinned to it), which overflows the chat's frame. This fits them
// to the frame and tells the chat the size the figure was made for, so the
// frame can keep its shape. Pages without Plotly figures are left alone.
(function () {
	var tries = 0;

	function fill(gd) {
		var el = gd.parentElement;
		while (el && el !== document.body) {
			el.style.width = '100%';
			el.style.height = '100%';
			el = el.parentElement;
		}
	}

	function fit() {
		var P = window.Plotly;
		var gds = Array.prototype.slice.call(document.querySelectorAll('.js-plotly-plot'));
		if (!P || !P.Plots || !gds.length) {
			if (++tries < 100) setTimeout(fit, 100);
			return;
		}
		var single = gds.length === 1;
		var style = document.createElement('style');
		style.textContent = single
			? 'html,body{margin:0;padding:0;height:100%;overflow:hidden}'
			: 'html,body{margin:0;padding:0}';
		document.head.appendChild(style);

		if (single) {
			var layout = gds[0].layout || {};
			var w = Number(layout.width);
			var h = Number(layout.height);
			if (w > 0 && h > 0 && window.parent !== window) {
				window.parent.postMessage({ type: 'weather-skills:figure-size', width: w, height: h }, '*');
			}
			fill(gds[0]);
		}
		gds.forEach(function (gd) {
			// relayout({width: null}) throws in some Plotly versions; deleting
			// the fixed size and resizing works across them.
			delete gd.layout.width;
			gd.style.width = '100%';
			if (gd.parentElement) gd.parentElement.style.width = '100%';
			if (single) delete gd.layout.height;
			gd.layout.autosize = true;
			P.Plots.resize(gd);
		});
		window.addEventListener('resize', function () {
			gds.forEach(function (gd) {
				P.Plots.resize(gd);
			});
		});
	}

	if (document.readyState === 'complete') fit();
	else window.addEventListener('load', fit);
})();
