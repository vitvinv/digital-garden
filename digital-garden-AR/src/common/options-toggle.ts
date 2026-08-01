// This is a component file. You can use this file to define a custom component for your project.
// This component will appear as a custom component in the editor.

import * as ecs from '@8thwall/ecs'  // This is how you access the ecs library.

ecs.registerComponent({
  name: 'options-toggle',
  schema: {
    selectorButton: ecs.eid,
    options: ecs.eid,
  },
  stateMachine: ({world, eid, defineState}) => {
    defineState('hide-options')
      .onEnter(({schema}) => {
        ecs.Hidden.set(world, schema.options)
      })
      .onEvent(ecs.input.UI_CLICK, 'show-options')
      .initial()

    defineState('show-options')
      .onEnter(({schema}) => {
        ecs.Hidden.remove(world, schema.options)
      })
      .onEvent(ecs.input.UI_CLICK, 'hide-options')
  },
})
