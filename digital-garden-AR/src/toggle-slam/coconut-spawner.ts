import * as ecs from '@8thwall/ecs'
import Coconut from './coconut'

ecs.registerComponent({
  name: 'Coconut Spawner',
  stateMachine: ({world, eid, schemaAttribute, dataAttribute}) => {
    ecs.defineState('default')
      .initial()
      .onEnter(() => {
        if (ecs.Hidden.has(world, world.getParent(eid))) {
          return
        }

        const ent = world.createEntity()

        world.setParent(ent, eid)
        world.setPosition(ent, 0, 0, 0)
        ecs.SphereGeometry.set(world, ent, {
          radius: 0.05,
        })

        ecs.Material.set(world, ent, {
          r: 210,
          g: 105,
          b: 30,
        })

        ecs.Collider.set(world, ent, {
          mass: 1,
          shape: ecs.ColliderShape.Sphere,
          radius: 0.05,
        })

        Coconut.set(world, ent)
      })
      .wait(1000, 'cooldown')

    ecs.defineState('cooldown')
      .wait(1000, 'default')
  },
})
