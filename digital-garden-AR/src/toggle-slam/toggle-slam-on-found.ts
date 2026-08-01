import * as ecs from '@8thwall/ecs'

ecs.registerComponent({
  name: 'Toggle SLAM on Found',
  schema: {
    // @required
    worldContent: ecs.eid,
    imageTargetName: ecs.string,
  },
  schemaDefaults: {
    imageTargetName: '',
  },
  stateMachine: ({world, eid, schemaAttribute, dataAttribute}) => {
    ecs.defineState('default')
      .initial()
      .onEnter(() => {
        const {worldContent} = schemaAttribute.get(eid)

        ecs.Camera.mutate(world, world.camera.getActiveEid(), (c) => {
          c.disableWorldTracking = true
        })

        ecs.Hidden.set(world, worldContent)
      })
      .listen(world.events.globalId, 'reality.imagefound', (e) => {
        const {name, position, rotation, scale} = e.data as any
        const {imageTargetName, worldContent} = schemaAttribute.get(eid)

        if (name === imageTargetName) {
          ecs.Camera.mutate(world, world.camera.getActiveEid(), (c) => {
            c.disableWorldTracking = false
          })

          // console.log(e.data)
          world.setScale(worldContent, scale, scale, scale)
          // world.setQuaternion(worldContent, rotation.x, rotation.y, rotation.z, rotation.w)
          world.setPosition(worldContent, position.x, position.y, position.z)
          ecs.Hidden.remove(world, worldContent)
        }
      })
  },
})
