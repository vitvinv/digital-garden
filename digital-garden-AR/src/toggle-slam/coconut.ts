import * as ecs from '@8thwall/ecs'

const Coconut = ecs.registerComponent({
  name: 'Coconut',
  stateMachine: ({world, eid}) => {
    ecs.defineState('default')
      .initial()
      .wait(5000, 'delete')

    ecs.defineState('delete')
      .onEnter(() => {
        world.deleteEntity(eid)
      })
  },
})

export default Coconut
