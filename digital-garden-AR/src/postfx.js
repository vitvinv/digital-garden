const DEFAULT_CONFIG = {
  enabled: true,
  debugView: null,
  pixelate: {
    enabled: false,
    pixelSize: 4,
    maxInternalWidth: 960,
    smoothUpscale: false,
  },
  bloom: {
    enabled: true,
    intensity: 0.8,
    threshold: 0.4,
    radius: 0.8,
  },
}

const CONFIG_LIMITS = {
  pixelSize: [1, 32],
  maxInternalWidth: [64, 4096],
  intensity: [0, 4],
  threshold: [0, 4],
  radius: [0, 1],
}

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

const numberOr = (value, fallback) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

const cloneConfig = config => ({
  enabled: config.enabled,
  debugView: config.debugView,
  pixelate: {...config.pixelate},
  bloom: {...config.bloom},
})

const normalizeConfig = (input = {}) => {
  const source = input || {}
  const pixelate = source.pixelate || {}
  const bloom = source.bloom || {}

  return {
    enabled: source.enabled !== false,
    debugView: ['bright', 'blur'].includes(source.debugView) ? source.debugView : null,
    pixelate: {
      enabled: pixelate.enabled !== false,
      pixelSize: clamp(
        numberOr(pixelate.pixelSize, DEFAULT_CONFIG.pixelate.pixelSize),
        ...CONFIG_LIMITS.pixelSize
      ),
      maxInternalWidth: Math.round(clamp(
        numberOr(pixelate.maxInternalWidth, DEFAULT_CONFIG.pixelate.maxInternalWidth),
        ...CONFIG_LIMITS.maxInternalWidth
      )),
      smoothUpscale: pixelate.smoothUpscale === true,
    },
    bloom: {
      enabled: bloom.enabled !== false,
      intensity: clamp(
        numberOr(bloom.intensity, DEFAULT_CONFIG.bloom.intensity),
        ...CONFIG_LIMITS.intensity
      ),
      threshold: clamp(
        numberOr(bloom.threshold, DEFAULT_CONFIG.bloom.threshold),
        ...CONFIG_LIMITS.threshold
      ),
      radius: clamp(
        numberOr(bloom.radius, DEFAULT_CONFIG.bloom.radius),
        ...CONFIG_LIMITS.radius
      ),
    },
  }
}

const mergeConfig = (base, override) => normalizeConfig({
  ...base,
  ...override,
  pixelate: {
    ...base.pixelate,
    ...(override && override.pixelate),
  },
  bloom: {
    ...base.bloom,
    ...(override && override.bloom),
  },
})

const parseBoolean = value => {
  if (value === null || value === undefined) {
    return undefined
  }
  if (['0', 'false', 'off', 'no'].includes(String(value).toLowerCase())) {
    return false
  }
  if (['1', 'true', 'on', 'yes'].includes(String(value).toLowerCase())) {
    return true
  }
  return undefined
}

const getUrlOverrides = () => {
  const params = new URLSearchParams(window.location.search)
  const pixelate = parseBoolean(params.get('pixelate'))
  const bloom = parseBoolean(params.get('bloomEnabled'))
  const enabled = parseBoolean(params.get('fx'))
  const debugView = params.get('bloomDebug')
  const override = {}

  if (enabled !== undefined) {
    override.enabled = enabled
  }
  if (debugView === 'bright' || debugView === 'blur') {
    override.debugView = debugView
  }
  if (pixelate !== undefined || params.has('pixelSize') || params.has('maxInternalWidth')) {
    override.pixelate = {}
    if (pixelate !== undefined) {
      override.pixelate.enabled = pixelate
    }
    if (params.has('pixelSize')) {
      override.pixelate.pixelSize = params.get('pixelSize')
    }
    if (params.has('maxInternalWidth')) {
      override.pixelate.maxInternalWidth = params.get('maxInternalWidth')
    }
  }
  if (bloom !== undefined || params.has('bloom') || params.has('bloomThreshold') || params.has('bloomRadius')) {
    override.bloom = {}
    if (bloom !== undefined) {
      override.bloom.enabled = bloom
    }
    if (params.has('bloom')) {
      override.bloom.intensity = params.get('bloom')
    }
    if (params.has('bloomThreshold')) {
      override.bloom.threshold = params.get('bloomThreshold')
    }
    if (params.has('bloomRadius')) {
      override.bloom.radius = params.get('bloomRadius')
    }
  }

  return override
}

const getThree = () => {
  if (!window.THREE) {
    throw new Error('PostFX requires the 8th Wall THREE global.')
  }
  return window.THREE
}

const setTextureFilter = (texture, THREE, smooth) => {
  texture.generateMipmaps = false
  texture.minFilter = smooth ? THREE.LinearFilter : THREE.NearestFilter
  texture.magFilter = smooth ? THREE.LinearFilter : THREE.NearestFilter
  texture.needsUpdate = true
}

const setLinearColorSpace = texture => {
  if ('colorSpace' in texture && window.THREE.NoColorSpace !== undefined) {
    texture.colorSpace = window.THREE.NoColorSpace
  } else if ('encoding' in texture && window.THREE.LinearEncoding !== undefined) {
    texture.encoding = window.THREE.LinearEncoding
  }
}

const makeRenderTarget = (THREE, width, height, options = {}) => {
  const target = new THREE.WebGLRenderTarget(width, height, {
    depthBuffer: options.depthBuffer === true,
    stencilBuffer: options.stencilBuffer === true,
    type: options.type,
    format: THREE.RGBAFormat,
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    generateMipmaps: false,
  })
  setLinearColorSpace(target.texture)
  return target
}

const makeScene = (THREE, material) => {
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
  const geometry = new THREE.PlaneGeometry(2, 2)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.frustumCulled = false
  scene.add(mesh)
  scene.add(camera)
  return {scene, camera, geometry, mesh}
}

const FULLSCREEN_VERTEX = `
  varying vec2 vUv;

  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`

const BRIGHT_FRAGMENT = `
  uniform sampler2D uScene;
  uniform float uThreshold;
  varying vec2 vUv;

  void main() {
    vec4 source = texture2D(uScene, vUv);
    float brightness = max(max(source.r, source.g), source.b);
    float contribution = max(brightness - uThreshold, 0.0);
    gl_FragColor = vec4(source.rgb * contribution, contribution);
  }
`

const BLUR_FRAGMENT = `
  uniform sampler2D uTexture;
  uniform vec2 uTexelSize;
  uniform vec2 uDirection;
  uniform float uRadius;
  varying vec2 vUv;

  void main() {
    vec2 offset = uTexelSize * uDirection * uRadius;
    vec4 color = texture2D(uTexture, vUv) * 0.227027;
    color += texture2D(uTexture, vUv + offset * 1.384615) * 0.316216;
    color += texture2D(uTexture, vUv - offset * 1.384615) * 0.316216;
    color += texture2D(uTexture, vUv + offset * 3.230769) * 0.070270;
    color += texture2D(uTexture, vUv - offset * 3.230769) * 0.070270;
    gl_FragColor = color;
  }
`

const COMPOSITE_FRAGMENT = `
  uniform sampler2D uScene;
  uniform sampler2D uBloom;
  uniform float uBloomIntensity;
  uniform bool uHasBloom;
  uniform int uDebugMode;
  uniform float uDebugBoost;
  varying vec2 vUv;

  void main() {
    vec4 scene = texture2D(uScene, vUv);
    vec4 bloomSample = texture2D(uBloom, vUv);

    if (uDebugMode > 0) {
      gl_FragColor = vec4(bloomSample.rgb * uDebugBoost, 1.0);
    } else {
      vec3 bloom = bloomSample.rgb * uBloomIntensity;
      float bloomAlpha = clamp(bloomSample.a * uBloomIntensity, 0.0, 1.0);
      gl_FragColor = vec4(scene.rgb + bloom, max(scene.a, bloomAlpha));
    }
    // The scene is accumulated in a linear render target, so convert the final
    // composite to the output color space (sRGB canvas) here. Without this the
    // whole image is written as raw linear values and appears far too dark.
    #include <colorspace_fragment>
  }
`

const createMaterial = (THREE, fragmentShader, uniforms, options = {}) => {
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: FULLSCREEN_VERTEX,
    fragmentShader,
    transparent: options.transparent === true,
    blending: options.blending || THREE.NoBlending,
    depthTest: false,
    depthWrite: false,
    toneMapped: false,
  })
  material.needsUpdate = true
  return material
}

const getCanvasCssSize = canvas => {
  const rect = canvas.getBoundingClientRect()
  return {
    width: Math.max(1, rect.width || window.innerWidth),
    height: Math.max(1, rect.height || window.innerHeight),
  }
}

const getInternalSize = (canvas, config) => {
  const cssSize = getCanvasCssSize(canvas)
  const pixelSize = config.pixelate.enabled ? config.pixelate.pixelSize : 1
  const width = Math.max(1, Math.min(
    config.pixelate.enabled ? Math.round(cssSize.width / pixelSize) : Math.round(canvas.width),
    config.pixelate.enabled ? config.pixelate.maxInternalWidth : Math.max(1, canvas.width)
  ))
  const aspect = cssSize.height / cssSize.width
  return {
    width,
    height: Math.max(1, Math.round(width * aspect)),
  }
}

const isMainRender = (renderer, mainScene, scene) => (
  scene === mainScene && renderer.getRenderTarget() === null
)

export const createPostFX = (world, initialConfig = {}) => {
  const THREE = getThree()
  const renderer = world.three.renderer
  let mainScene = world.three.scene
  const canvas = renderer.domElement
  const originalRender = renderer.render.bind(renderer)
  const stateKey = '__digitalGardenPostFX'

  if (renderer[stateKey]) {
    renderer[stateKey].dispose()
  }

  let config = mergeConfig(DEFAULT_CONFIG, initialConfig)
  let internalWidth = 0
  let internalHeight = 0
  let sceneTarget = null
  let brightTarget = null
  let blurTarget = null
  let targetsType = undefined
  let disposed = false
  let failed = false
  let renderCalls = 0
  let interceptedRenders = 0
  let bypassedRenders = 0
  let bypassedSceneRenders = 0
  let bypassedTargetRenders = 0
  let sceneChanges = 0
  let lastRoute = 'not-rendered'
  let lastError = null

  const brightMaterial = createMaterial(THREE, BRIGHT_FRAGMENT, {
    uScene: {value: null},
    uThreshold: {value: config.bloom.threshold},
  })
  const blurMaterial = createMaterial(THREE, BLUR_FRAGMENT, {
    uTexture: {value: null},
    uTexelSize: {value: new THREE.Vector2(1, 1)},
    uDirection: {value: new THREE.Vector2(1, 0)},
    uRadius: {value: config.bloom.radius},
  })
  const compositeMaterial = createMaterial(THREE, COMPOSITE_FRAGMENT, {
    uScene: {value: null},
    uBloom: {value: null},
    uBloomIntensity: {value: config.bloom.intensity},
    uHasBloom: {value: config.bloom.enabled && config.bloom.intensity > 0},
    uDebugMode: {value: config.debugView === 'bright' || config.debugView === 'blur' ? 1 : 0},
    uDebugBoost: {value: 4},
  }, {
    transparent: true,
    blending: THREE.NormalBlending,
  })

  const brightPass = makeScene(THREE, brightMaterial)
  const blurPass = makeScene(THREE, blurMaterial)
  const compositePass = makeScene(THREE, compositeMaterial)

  const disposeTarget = target => {
    if (target) {
      target.dispose()
    }
  }

  const disposeTargets = () => {
    disposeTarget(sceneTarget)
    disposeTarget(brightTarget)
    disposeTarget(blurTarget)
    sceneTarget = null
    brightTarget = null
    blurTarget = null
    internalWidth = 0
    internalHeight = 0
  }

  const chooseTargetType = () => {
    if (targetsType !== undefined) {
      return targetsType
    }
    if (THREE.HalfFloatType === undefined) {
      targetsType = undefined
      return targetsType
    }
    try {
      const gl = renderer.getContext()
      const supportsHalfFloat = gl && (
        (typeof WebGL2RenderingContext !== 'undefined' && gl instanceof WebGL2RenderingContext) ||
        gl.getExtension('EXT_color_buffer_half_float') ||
        gl.getExtension('EXT_color_buffer_float')
      )
      targetsType = supportsHalfFloat ? THREE.HalfFloatType : undefined
    } catch (error) {
      targetsType = undefined
    }
    return targetsType
  }

  const ensureTargets = () => {
    const size = getInternalSize(canvas, config)
    const type = chooseTargetType()
    if (
      sceneTarget &&
      internalWidth === size.width &&
      internalHeight === size.height &&
      targetsType === type
    ) {
      return
    }

    disposeTargets()
    internalWidth = size.width
    internalHeight = size.height
    targetsType = type

    sceneTarget = makeRenderTarget(THREE, internalWidth, internalHeight, {
      depthBuffer: true,
      stencilBuffer: true,
      type,
    })
    brightTarget = makeRenderTarget(THREE, internalWidth, internalHeight, {type})
    blurTarget = makeRenderTarget(THREE, internalWidth, internalHeight, {type})

    setTextureFilter(sceneTarget.texture, THREE, config.pixelate.smoothUpscale)
    setTextureFilter(brightTarget.texture, THREE, true)
    setTextureFilter(blurTarget.texture, THREE, true)
    compositeMaterial.uniforms.uScene.value = sceneTarget.texture
    compositeMaterial.uniforms.uBloom.value = blurTarget.texture
    brightMaterial.uniforms.uScene.value = sceneTarget.texture
    blurMaterial.uniforms.uTexelSize.value.set(1 / internalWidth, 1 / internalHeight)
  }

  const getDebugMode = () => {
    if (config.debugView === 'bright') {
      return 1
    }
    if (config.debugView === 'blur') {
      return 2
    }
    return 0
  }

  const updateMaterials = () => {
    brightMaterial.uniforms.uThreshold.value = config.bloom.threshold
    blurMaterial.uniforms.uRadius.value = config.bloom.radius
    compositeMaterial.uniforms.uBloomIntensity.value = config.bloom.intensity
    compositeMaterial.uniforms.uHasBloom.value = config.bloom.enabled && config.bloom.intensity > 0
    compositeMaterial.uniforms.uDebugMode.value = getDebugMode()
    setTextureFilter(sceneTarget && sceneTarget.texture, THREE, config.pixelate.smoothUpscale)
  }

  const renderPass = (pass, target) => {
    renderer.setRenderTarget(target)
    renderer.clear(true, true, false)
    originalRender(pass.scene, pass.camera)
  }

  const renderEffects = (scene, camera) => {
    ensureTargets()
    updateMaterials()

    const previousAutoClear = renderer.autoClear
    const previousAutoClearColor = renderer.autoClearColor
    const previousAutoClearDepth = renderer.autoClearDepth
    const previousAutoClearStencil = renderer.autoClearStencil
    const previousTarget = renderer.getRenderTarget()
    const previousClearColor = new THREE.Color()
    renderer.getClearColor(previousClearColor)
    const previousClearAlpha = renderer.getClearAlpha()
    const previousScissorTest = renderer.getScissorTest()
    const previousViewport = new THREE.Vector4()
    const previousScissor = new THREE.Vector4()
    renderer.getViewport(previousViewport)
    renderer.getScissor(previousScissor)

    try {
      renderer.setClearColor(0x000000, 0)
      renderer.autoClear = true
      renderer.autoClearColor = true
      renderer.autoClearDepth = true
      renderer.autoClearStencil = true

      renderer.setRenderTarget(sceneTarget)
      renderer.clear(true, true, true)
      originalRender(scene, camera)

      const debugMode = getDebugMode()
      const shouldBloom = debugMode > 0 || (config.bloom.enabled && config.bloom.intensity > 0)
      if (shouldBloom) {
        brightMaterial.uniforms.uThreshold.value = config.bloom.threshold
        renderPass(brightPass, brightTarget)

        if (debugMode === 1) {
          // Keep the unblurred extraction visible for threshold diagnostics.
          compositeMaterial.uniforms.uBloom.value = brightTarget.texture
        } else {
          blurMaterial.uniforms.uTexture.value = brightTarget.texture
          blurMaterial.uniforms.uDirection.value.set(1, 0)
          renderPass(blurPass, blurTarget)

          blurMaterial.uniforms.uTexture.value = blurTarget.texture
          blurMaterial.uniforms.uDirection.value.set(0, 1)
          renderPass(blurPass, brightTarget)

          compositeMaterial.uniforms.uBloom.value = brightTarget.texture
        }
      } else {
        compositeMaterial.uniforms.uBloom.value = blurTarget.texture
      }

      renderer.setRenderTarget(null)
      renderer.setScissorTest(false)
      renderer.autoClear = false
      renderer.autoClearColor = false
      renderer.clear(false, true, false)
      originalRender(compositePass.scene, compositePass.camera)
    } finally {
      renderer.setRenderTarget(previousTarget)
      renderer.autoClear = previousAutoClear
      renderer.autoClearColor = previousAutoClearColor
      renderer.autoClearDepth = previousAutoClearDepth
      renderer.autoClearStencil = previousAutoClearStencil
      renderer.setClearColor(previousClearColor, previousClearAlpha)
      renderer.setScissorTest(previousScissorTest)
      renderer.setViewport(previousViewport)
      renderer.setScissor(previousScissor)
    }
  }

  const wrappedRender = (scene, camera) => {
    renderCalls += 1

    // Re-read the scene from the world in case 8th Wall reassigned it
    // (e.g., when the camera starts tracking in the internal player).
    if (world.three.scene !== mainScene) {
      mainScene = world.three.scene
      sceneChanges += 1
    }

    const sceneMatches = scene === mainScene
    const usesDefaultTarget = renderer.getRenderTarget() === null
    const eligible = isMainRender(renderer, mainScene, scene)
    if (disposed || failed || !config.enabled || !eligible) {
      bypassedRenders += 1
      if (config.enabled && !disposed && !failed) {
        if (!sceneMatches) {
          bypassedSceneRenders += 1
          lastRoute = 'bypassed-scene-mismatch'
        } else if (!usesDefaultTarget) {
          bypassedTargetRenders += 1
          lastRoute = 'bypassed-nondefault-target'
        }
      } else if (disposed) {
        lastRoute = 'disposed'
      } else if (failed) {
        lastRoute = 'failed'
      } else {
        lastRoute = 'disabled'
      }
      return originalRender(scene, camera)
    }

    interceptedRenders += 1
    lastRoute = 'postfx'
    try {
      renderEffects(scene, camera)
    } catch (error) {
      failed = true
      lastError = error && error.stack ? error.stack : String(error)
      lastRoute = 'fallback-after-error'
      console.warn('[Digital Garden] PostFX disabled after a render error.', error)
      try {
        renderer.setRenderTarget(null)
        originalRender(scene, camera)
      } catch (fallbackError) {
        lastError = fallbackError && fallbackError.stack ? fallbackError.stack : String(fallbackError)
        console.warn('[Digital Garden] Direct render fallback failed.', fallbackError)
      }
    }
  }

  renderer.render = wrappedRender

  const api = {
    getConfig: () => cloneConfig(config),
    applyConfig: nextConfig => {
      config = normalizeConfig(nextConfig)
      failed = false
      ensureTargets()
      updateMaterials()
      return api.getConfig()
    },
    mergeConfig: patch => {
      config = mergeConfig(config, patch)
      failed = false
      ensureTargets()
      updateMaterials()
      return api.getConfig()
    },
    getDefaultConfig: () => cloneConfig(DEFAULT_CONFIG),
    getDiagnostics: () => ({
      renderCalls,
      interceptedRenders,
      bypassedRenders,
      bypassedSceneRenders,
      bypassedTargetRenders,
      sceneChanges,
      lastRoute,
      lastError,
      internalWidth,
      internalHeight,
      targetType: targetsType === undefined ? 'default' : targetsType,
      config: api.getConfig(),
    }),
    setDebugView: view => {
      config = normalizeConfig({...config, debugView: view})
      failed = false
      updateMaterials()
      return api.getConfig()
    },
    copyConfig: () => {
      const text = JSON.stringify(config, null, 2)
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(() => {})
      }
      console.log(text)
      return text
    },
    dispose: () => {
      if (disposed) {
        return
      }
      disposed = true
      renderer.render = originalRender
      disposeTargets()
      brightPass.geometry.dispose()
      blurPass.geometry.dispose()
      compositePass.geometry.dispose()
      brightMaterial.dispose()
      blurMaterial.dispose()
      compositeMaterial.dispose()
      if (renderer[stateKey] === api) {
        delete renderer[stateKey]
      }
    },
  }

  renderer[stateKey] = api
  ensureTargets()
  updateMaterials()
  return api
}

export const getPostFXConfig = () => normalizeConfig(require('./fx-config.json'))
export const getPostFXUrlOverrides = getUrlOverrides
export {DEFAULT_CONFIG, normalizeConfig}
