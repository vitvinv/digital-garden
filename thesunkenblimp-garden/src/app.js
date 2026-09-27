import fxConfig from './fx-config.json'
import {createPostFX, getPostFXUrlOverrides} from './postfx.js'

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
