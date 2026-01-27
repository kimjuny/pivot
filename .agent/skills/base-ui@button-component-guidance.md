---
title: Button
subtitle: A button component that can be rendered as another tag or focusable when disabled.
description: A high-quality, unstyled React button component that can be rendered as another tag or focusable when disabled.
---

# Button

<Meta name="description" content="A high-quality, unstyled React button component that can be rendered as another tag or focusable when disabled." />

## Demo

### Tailwind

This example shows how to implement the component using Tailwind CSS.

```tsx
/* index.tsx */
import * as React from 'react';
import { Button } from '@base-ui/react/button';

export default function ExampleButton() {
  return (
    <Button className="flex items-center justify-center h-10 px-3.5 m-0 outline-0 border border-gray-200 rounded-md bg-gray-50 font-inherit text-base font-medium leading-6 text-gray-900 select-none hover:data-[disabled]:bg-gray-50 hover:bg-gray-100 active:data-[disabled]:bg-gray-50 active:bg-gray-200 active:shadow-[inset_0_1px_3px_rgba(0,0,0,0.1)] active:border-t-gray-300 active:data-[disabled]:shadow-none active:data-[disabled]:border-t-gray-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-800 focus-visible:-outline-offset-1 data-[disabled]:text-gray-500">
      Submit
    </Button>
  );
}
```

## Anatomy

Import the component:

```jsx title="Anatomy"
import { Button } from '@base-ui/react/button';

<Button />;
```

## Examples

### Rendering as another tag

The button can remain keyboard accessible while being rendered as another tag, such as a `<div>`, by specifying `nativeButton={false}`.

```jsx title="Custom tag button" "nativeButton"
import { Button } from '@base-ui/react/button';

<Button render={<div />} nativeButton={false}>
  Button that can contain complex children
</Button>;
```

### Loading states

For buttons that enter a loading state after being clicked, specify the `focusableWhenDisabled` prop to ensure focus remains on the button when it becomes disabled. This prevents focus from being lost and maintains the tab order.

## Demo

### Tailwind

This example shows how to implement the component using Tailwind CSS.

```tsx
/* index.tsx */
'use client';
import * as React from 'react';
import { Button } from '@base-ui/react/button';

export default function ExampleButton() {
  const [loading, setLoading] = React.useState(false);

  return (
    <Button
      className="flex items-center justify-center h-10 px-3.5 m-0 outline-0 border border-gray-200 rounded-md bg-gray-50 font-inherit text-base font-medium leading-6 text-gray-900 select-none hover:data-[disabled]:bg-gray-50 hover:bg-gray-100 active:data-[disabled]:bg-gray-50 active:bg-gray-200 active:shadow-[inset_0_1px_3px_rgba(0,0,0,0.1)] active:border-t-gray-300 active:data-[disabled]:shadow-none active:data-[disabled]:border-t-gray-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-800 focus-visible:-outline-offset-1 data-[disabled]:text-gray-500"
      disabled={loading}
      focusableWhenDisabled
      onClick={() => {
        setLoading(true);
        setTimeout(() => {
          setLoading(false);
        }, 4000);
      }}
    >
      {loading ? 'Submitting' : 'Submit'}
    </Button>
  );
}
```

## API reference

A button component that can be used to trigger actions.
Renders a `<button>` element.

**Button Props:**

| Prop                  | Type                                                                        | Default | Description                                                                                                                                                                                  |
| :-------------------- | :-------------------------------------------------------------------------- | :------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| focusableWhenDisabled | `boolean`                                                                   | `false` | Whether the button should be focusable when disabled.                                                                                                                                        |
| nativeButton          | `boolean`                                                                   | `true`  | Whether the component renders a native `<button>` element when replacing it&#xA;via the `render` prop.&#xA;Set to `false` if the rendered element is not a button (e.g. `<div>`).            |
| className             | `string \| ((state: Button.State) => string \| undefined)`                  | -       | CSS class applied to the element, or a function that&#xA;returns a class based on the component’s state.                                                                                     |
| style                 | `CSSProperties \| ((state: Button.State) => CSSProperties \| undefined)`    | -       | -                                                                                                                                                                                            |
| render                | `ReactElement \| ((props: HTMLProps, state: Button.State) => ReactElement)` | -       | Allows you to replace the component’s HTML element&#xA;with a different tag, or compose it with another component.Accepts a `ReactElement` or a function that returns the element to render. |

**Button Data Attributes:**

| Attribute     | Type | Description                          |
| :------------ | :--- | :----------------------------------- |
| data-disabled | -    | Present when the button is disabled. |