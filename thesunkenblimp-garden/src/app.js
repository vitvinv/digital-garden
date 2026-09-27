import fxConfig from './fx-config.json'
import scene from './.expanse.json'
import {createPostFX, getPostFXUrlOverrides} from './postfx.js'

// ── staged growth (demo garden) ────────────────────────────────────────────
// Runs before ecs.application.init(scene) (this module executes before the
// entry body), so mutating the imported scene JSON swaps the garden GLB.
// The Garden object's model must point at assets/gardens/garden_stage_01.glb
// (set in 8th Wall Studio); this code rewrites the stage by elapsed time.
const STAGE_COUNT = 10
const STAGE_WINDOW_MS = 30 * 60 * 1000 // 30 min per stage → full bloom in 5 h
const PLANTED_KEY = 'garden_planted_thesunkenblimp' // set by the welcome page
const GARDEN_GLB_RE = /assets\/gardens\/garden_stage_\d+\.glb$/

const currentStage = () => {
  let planted = null
  try { planted = Number(window.localStorage.getItem(PLANTED_KEY)) || null } catch (e) { planted = null }
  if (!planted) return 1
  return Math.min(STAGE_COUNT, 1 + Math.floor((Date.now() - planted) / STAGE_WINDOW_MS))
}

const gardenObject = Object.values(scene.objects || {}).find((obj) => {
  const asset = obj && obj.gltfModel && obj.gltfModel.src && obj.gltfModel.src.asset
  return typeof asset === 'string' && GARDEN_GLB_RE.test(asset)
})
if (gardenObject) {
  const stage = currentStage()
  gardenObject.gltfModel.src.asset = `assets/gardens/garden_stage_${String(stage).padStart(2, '0')}.glb`
  console.info(`[Garden] growth stage ${stage}/${STAGE_COUNT}`)
} else {
  console.warn('[Garden] no garden_stage_*.glb model in scene — growth stage not applied')
}

// If the tab stays open across a stage boundary, reload into the next stage.
const bootStage = currentStage()
window.setInterval(() => {
  if (currentStage() !== bootStage) window.location.reload()
}, 60 * 1000)

let postFXInitializing = false

const initPostFX = () => {
  const world = window.ecs?.application?.getWorld?.()
  if (!world || window.FX || postFXInitializing) {
    return Boolean(world)
  }

  postFXInitializing = true

  const urlOverrides = getPostFXUrlOverrides()

  try {
    const fx = createPostFX(world, {
      ...fxConfig,
      ...urlOverrides,
      pixelate: {
        ...fxConfig.pixelate,
        ...urlOverrides.pixelate,
      },
      bloom: {
        ...fxConfig.bloom,
        ...urlOverrides.bloom,
      },
    })

    window.FX = fx
    console.info('[Digital Garden] PostFX ready. Use window.FX.getConfig() or window.FX.applyConfig({...}).')
  } catch (error) {
    console.warn('[Digital Garden] PostFX unavailable; using the direct renderer.', error)
  }

  return true
}

const onxrloaded = () => {
  XR8.XrController.configure({
    imageTargetData: [
      require('../image-targets/ENG-digital-garden-sticker.json'),
    ],
  })
  XR8.addCameraPipelineModule(LandingPage.pipelineModule())
}

window.addEventListener('ecsInit', initPostFX)
const postFXPoll = window.setInterval(() => {
  if (initPostFX()) {
    window.clearInterval(postFXPoll)
  }
}, 50)
window.XR8 ? onxrloaded() : window.addEventListener('xrloaded', onxrloaded)
