import fxConfig from './fx-config.json'
import scene from './.expanse.json'
import {createPostFX, getPostFXUrlOverrides} from './postfx.js'

// ── staged growth (demo garden) ────────────────────────────────────────────
// Runs before ecs.application.init(scene) (this module executes before the
// entry body), so mutating the imported scene JSON swaps the garden GLB.
// The Garden object's model must point at assets/gardens/garden_stage_01.glb
// (set in 8th Wall Studio); this code rewrites the stage by elapsed time.
const STAGE_COUNT = 10
const STAGE_WINDOW_MS = 6 * 60 * 1000 // 6 min per stage → full bloom in 1 h
const PLANTED_KEY = 'garden_planted_thesunkenblimp' // set by the welcome page
const GARDEN_GLB_RE = /assets\/gardens\/garden_stage_\d+\.glb$/

const currentStage = () => {
  let planted = null
  try { planted = Number(window.localStorage.getItem(PLANTED_KEY)) || null } catch (e) { planted = null }
  if (!planted) return 1
  return Math.min(STAGE_COUNT, 1 + Math.floor((Date.now() - planted) / STAGE_WINDOW_MS))
}

const stage = currentStage()
const wantAsset = `assets/gardens/garden_stage_${String(stage).padStart(2, '0')}.glb`
const stageObjects = Object.values(scene.objects || {}).filter((obj) => {
  const asset = obj && obj.gltfModel && obj.gltfModel.src && obj.gltfModel.src.asset
  return typeof asset === 'string' && GARDEN_GLB_RE.test(asset)
})
if (stageObjects.length) {
  // Keep exactly one stage object (the current stage); drop the rest before
  // ecs init so they neither render nor preload their GLBs.
  let kept = stageObjects.find((obj) => obj.gltfModel.src.asset === wantAsset)
  if (!kept) {
    kept = stageObjects[0]
    kept.gltfModel.src.asset = wantAsset
  }
  for (const obj of stageObjects) {
    if (obj !== kept) delete scene.objects[obj.id]
  }
  console.info(`[Garden] growth stage ${stage}/${STAGE_COUNT} (${wantAsset})`)
} else {
  console.warn('[Garden] no garden_stage_*.glb objects in scene — growth stage not applied')
}

// If the user returns to the tab in a later growth stage, reload into it.
// Gating on visibilitychange means a reload only fires when the tab becomes
// visible again — never mid-session, so the camera pipeline is not restarted
// while AR is running (a restarted feed can come up flipped).
const bootStage = currentStage()
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && currentStage() !== bootStage) window.location.reload()
})

// Info pill: countdown to full bloom (same wording/format as the welcome page).
const TOTAL_MS = STAGE_WINDOW_MS * STAGE_COUNT
const infoCountdown = document.getElementById('garden-countdown')
const updateCountdown = () => {
  if (!infoCountdown) return
  let planted = null
  try { planted = Number(window.localStorage.getItem(PLANTED_KEY)) || null } catch (e) { planted = null }
  if (!planted) {
    infoCountdown.style.display = 'none'
    return
  }
  const remaining = TOTAL_MS - (Date.now() - planted)
  if (remaining <= 0) {
    infoCountdown.textContent = 'in full bloom.'
  } else if (remaining < 60 * 1000) {
    infoCountdown.textContent = 'full bloom any minute now.'
  } else {
    const mins = Math.max(1, Math.round(remaining / (60 * 1000)))
    const h = Math.floor(mins / 60)
    const m = mins % 60
    infoCountdown.textContent = h === 0
      ? `full bloom in ${m} min.`
      : (m === 0 ? `full bloom in ${h} h.` : `full bloom in ${h} h ${m} min.`)
  }
  infoCountdown.style.display = 'block'
}
updateCountdown()
window.setInterval(updateCountdown, 60 * 1000)

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
      require('../image-targets/thesunkengarden-target.json'),
    ],
  })
  // Camera-error guard: the only error UI the removed LandingPage provided.
  // The browser's own permission grant persists per site on HTTPS, so the
  // per-visit confirmation is gone; this overlay only appears on failure.
  XR8.addCameraPipelineModule({
    name: 'garden-camera-guard',
    onCameraStatusChange: ({ status }) => {
      if (status !== 'error' || document.getElementById('garden-camera-error')) return
      const el = document.createElement('div')
      el.id = 'garden-camera-error'
      el.textContent = 'Camera access is needed to see the garden. Allow it in browser site settings, then reload.'
      el.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:92vw;background:rgba(255,255,255,.85);color:#111111;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.4;padding:6px 12px;border-radius:999px;z-index:9999;text-align:center;'
      document.body.appendChild(el)
    },
  })
}

window.addEventListener('ecsInit', initPostFX)
const postFXPoll = window.setInterval(() => {
  if (initPostFX()) {
    window.clearInterval(postFXPoll)
  }
}, 50)
window.XR8 ? onxrloaded() : window.addEventListener('xrloaded', onxrloaded)
