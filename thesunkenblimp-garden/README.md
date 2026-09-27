# Digital Garden

This is my art project (work in progress). Each garden is a sticker placed in public space. Anyone can scan this sticker with a phone camera and see a 3D garden inside it, that grows as days are passing by. You can walk past that sticker every day and see the garden growing. I am also planning to add a feature to "water" this garden to speed up its growth or perhaps support its life.

![Preview of the garden image target project open in the editor](./src/assets/preview.png)

<details><summary>Try it out</summary>

Scan the garden sticker image with your phone camera.

<img alt="Garden Sticker Image Target" src="./image-targets/digital-garden-sticker_original.png" width=400 />

</details>

## Usage

1. [Install the Desktop App](https://8thwall.org/downloads)
2. On this repository, click Code > Download zip
3. Unzip the folder to the location you'd like to work in
4. In the desktop app, click "Open" and select the folder
5. To connect to a mobile device, follow [these instructions](https://8th.io/connect-device)
6. When importing your own targets, please see [this guide](https://8thwall.org/docs/studio/guides/xr/image-targets) for more information
7. Recommended: Track your files using [git](https://git-scm.com/about) to avoid losing progress

### Visual effects

Bloom and PS-1-style pixelation are configured in [`src/fx-config.json`](./src/fx-config.json), so each garden project can keep its own settings. The effects are enabled by default and the internal resolution is based on `pixelSize` in CSS pixels, keeping the block size consistent across device resolutions.

While testing in the Desktop App simulator, use the browser console:

```js
window.FX.getConfig()
window.FX.applyConfig({
  enabled: true,
  pixelate: {enabled: true, pixelSize: 4, maxInternalWidth: 960, smoothUpscale: false},
  bloom: {enabled: true, intensity: 0.8, threshold: 0.4, radius: 0.8},
})
window.FX.copyConfig()
```

`applyConfig()` replaces the full settings object live. `copyConfig()` logs the current JSON and attempts to copy it to the clipboard for saving back into `src/fx-config.json`. URL overrides are also available for quick tests, for example `?pixelSize=6&bloom=1.2&pixelate=off`.

For bloom diagnosis, add `?bloomDebug=bright` to show the extracted bright pixels or `?bloomDebug=blur` to show the blurred bloom texture. The console command `window.FX.getDiagnostics()` reports whether the main render was intercepted, bypassed because a non-default render target was active, or disabled after an error.

## Deployment

This project contains Github Actions configuration for deployment to Github Pages, which triggers automatically by pushing the `main` branch. You can also follow the publishing instructions here: https://8thwall.org/docs/getting-started/publishing to publish to any other web host.

## Questions?

Please raise any questions on [Github Discussions](https://github.com/orgs/8thwall/discussions) or join the [Discord](https://8th.io/discord) to connect with the community.
