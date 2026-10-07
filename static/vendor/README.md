# Vendored browser assets

The app serves these locally so campus internet/CDN outages do not disable event UI.

| npm package | Version | Asset | License |
|---|---|---|---|
| socket.io-client | 4.7.5 | dist/socket.io.min.js | socket.io.LICENSE (MIT) |
| chart.js | 4.4.7 | dist/chart.umd.js | chart.LICENSE (MIT) |
| @zxing/browser | 0.1.5 | umd/zxing-browser.min.js | zxing.LICENSE (MIT) |

Retrieved using `npm pack` at these exact versions. Preserve package licenses when
updating. No npm runtime/build step is required. Do not add correct answers or passwords
here. Source maps are omitted; app-side code remains readable in static/js.
