const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const webpack = require('webpack')

const PLANT_GLB_RE = /(assets\/plants\/[A-Za-z0-9_./-]+\.glb)(?!\?v=)/g

const plantAssetsRev = (srcDir) => {
  const dir = path.join(srcDir, 'assets', 'plants')
  const hash = crypto.createHash('sha256')
  let files = []
  try {
    files = fs.readdirSync(dir).filter(f => f.endsWith('.glb')).sort()
  } catch (err) {
    // no plants dir yet - empty rev
  }
  for (const file of files) {
    hash.update(file)
    hash.update(fs.readFileSync(path.join(dir, file)))
  }
  return hash.digest('hex').slice(0, 8)
}

const createPlantCacheBustPlugin = ({srcDir}) => ({
  apply: (compiler) => {
    if (!srcDir) {
      throw new Error('createPlantCacheBustPlugin called without srcDir')
    }
    compiler.hooks.compilation.tap('PlantCacheBustPlugin', (compilation) => {
      compilation.hooks.processAssets.tap(
        {
          name: 'PlantCacheBustPlugin',
          stage: webpack.Compilation.PROCESS_ASSETS_STAGE_SUMMARIZE,
        },
        () => {
          const rev = process.env.GITHUB_SHA
            ? process.env.GITHUB_SHA.slice(0, 8)
            : plantAssetsRev(srcDir)

          const assets = compilation.assets
          const bundleNames = Object.keys(assets)
            .filter(name => /^bundle\.[0-9a-f]{20}\.js$/.test(name))

          Object.keys(assets).forEach(name => {
            const source = assets[name].source()
            const text = Buffer.isBuffer(source) ? source.toString('utf8') : source
            if (typeof text !== 'string') {
              return
            }
            let out = text
            if (name === 'index.html' && bundleNames.length > 0) {
              out = out.replace(/src="bundle\.js"/, `src="${bundleNames[0]}"`)
            }
            if (out.includes('assets/plants/')) {
              out = out.replace(PLANT_GLB_RE, (match, ref) => `${ref}?v=${rev}`)
            }
            if (out !== text) {
              compilation.updateAsset(
                name,
                new webpack.sources.RawSource(out)
              )
            }
          })
        }
      )
    })
  },
})

module.exports = createPlantCacheBustPlugin