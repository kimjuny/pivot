# Input

---
title: Input
subtitle: A native input element that automatically works with Field.
description: A high-quality, unstyled React input component.
---

## Demo

### Tailwind

This example shows how to implement the component using Tailwind CSS.

```tsx
/* index.tsx */
import { Input } from '@base-ui/react/input';

export default function ExampleInput() {
  return (
    <label className="flex flex-col items-start gap-1">
      <span className="text-sm font-medium text-gray-900">Name</span>
      <Input
        placeholder="Enter your name"
        className="h-10 w-56 rounded-md border border-gray-200 pl-3.5 text-base text-gray-900 focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-blue-800"
      />
    </label>
  );
}
```

## Usage guidelines

- **Form controls must have an accessible name**: It can be created using a `<label>` element or the `Field` component. See the [forms guide](/react/handbook/forms.md).

## Anatomy

Import the component and use it as a single part:

```jsx title="Anatomy"
import { Input } from '@base-ui/react/input';

<Input />;
```

## API reference

A native input element that automatically works with [Field](https://base-ui.com/react/components/field).
Renders an `<input>` element.

**Input Props:**

| Prop          | Type                                                                        | Default | Description                                                                                                                                                                                  |
| :------------ | :-------------------------------------------------------------------------- | :------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| defaultValue  | `string \| number \| string[]`                                              | -       | -                                                                                                                                                                                            |
| onValueChange | `((value: string, eventDetails: Field.Control.ChangeEventDetails) => void)` | -       | Callback fired when the `value` changes. Use when controlled.                                                                                                                                |
| className     | `string \| ((state: Input.State) => string \| undefined)`                   | -       | CSS class applied to the element, or a function that&#xA;returns a class based on the component’s state.                                                                                     |
| style         | `CSSProperties \| ((state: Input.State) => CSSProperties \| undefined)`     | -       | \*                                                                                                                                                                                           |
| render        | `ReactElement \| ((props: HTMLProps, state: Input.State) => ReactElement)`  | -       | Allows you to replace the component’s HTML element&#xA;with a different tag, or compose it with another component.Accepts a `ReactElement` or a function that returns the element to render. |

**Input Data Attributes:**

| Attribute     | Type | Description                                                              |
| :------------ | :--- | :----------------------------------------------------------------------- |
| data-disabled | -    | Present when the input is disabled.                                      |
| data-valid    | -    | Present when the input is in valid state (when wrapped in Field.Root).   |
| data-invalid  | -    | Present when the input is in invalid state (when wrapped in Field.Root). |
| data-dirty    | -    | Present when the input's value has changed (when wrapped in Field.Root). |
| data-touched  | -    | Present when the input has been touched (when wrapped in Field.Root).    |
| data-filled   | -    | Present when the input is filled (when wrapped in Field.Root).           |
| data-focused  | -    | Present when the input is focused (when wrapped in Field.Root).          |