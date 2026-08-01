import * as ecs from '@8thwall/ecs'

ecs.registerComponent({
  name: 'Pause Video on Image Target Lost',
  schema: {
    // @required
    videoPlayer: ecs.eid,
    imageTargetName: ecs.string,
  },
  schemaDefaults: {
    imageTargetName: '',
  },
  stateMachine: ({world, eid, schemaAttribute, dataAttribute}) => {
    ecs.defineState('default')
      .initial()
      .listen(world.events.globalId, 'reality.imagefound', (e) => {
        const {name} = e.data as any
        const {imageTargetName, videoPlayer} = schemaAttribute.get(eid)

        if (name === imageTargetName) {
          ecs.VideoControls.mutate(world, videoPlayer, (c) => {
            c.paused = false
          })
        }
      })
      .listen(world.events.globalId, 'reality.imagelost', (e) => {
        const {name} = e.data as any
        const {imageTargetName, videoPlayer} = schemaAttribute.get(eid)

        if (name === imageTargetName) {
          ecs.VideoControls.mutate(world, videoPlayer, (c) => {
            c.paused = true
          })
        }
      })
  },
})
