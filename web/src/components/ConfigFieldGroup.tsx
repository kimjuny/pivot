import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

/**
 * Shared manifest-driven field definition used by provider configuration dialogs.
 */
export interface ConfigFieldDefinition {
  /** Stable field key persisted in auth/runtime config objects. */
  key: string;
  /** User-facing field label. */
  label: string;
  /** Visual input type used by the dialog. */
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  /** Whether the field must be provided before saving. */
  required: boolean;
  /** Optional placeholder shown when the field is empty. */
  placeholder?: string | null;
  /** Optional helper text rendered below the field. */
  description?: string | null;
}

interface ConfigFieldGroupProps {
  title: string;
  description: string;
  fields: ConfigFieldDefinition[];
  values: Record<string, string>;
  onChange: (fieldKey: string, value: string) => void;
}

/**
 * Renders a schema-driven group of provider configuration fields.
 * Why: channel and web-search bindings use the same manifest contract, so a
 * shared renderer keeps the dialogs visually aligned and easier to extend.
 */
function ConfigFieldGroup({
  title,
  description,
  fields,
  values,
  onChange,
}: ConfigFieldGroupProps) {
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{description}</div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {fields.map((field) => (
          <div key={field.key} className={field.type === 'textarea' ? 'space-y-2 md:col-span-2' : 'space-y-2'}>
            <Label htmlFor={field.key}>
              {field.label}
              {field.required ? ' *' : ''}
            </Label>
            <ConfigFieldInput
              field={field}
              value={values[field.key] ?? ''}
              onChange={(value) => onChange(field.key, value)}
            />
            {field.description && (
              <div className="text-xs text-muted-foreground">{field.description}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

interface ConfigFieldInputProps {
  field: ConfigFieldDefinition;
  value: string;
  onChange: (value: string) => void;
}

/**
 * Renders one manifest-driven field input.
 */
function ConfigFieldInput({ field, value, onChange }: ConfigFieldInputProps) {
  if (field.type === 'textarea') {
    return (
      <Textarea
        id={field.key}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={field.placeholder ?? undefined}
      />
    );
  }

  if (field.type === 'boolean') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
        <Switch checked={value === 'true'} onCheckedChange={(checked) => onChange(String(checked))} />
        <span className="text-sm text-foreground">{value === 'true' ? 'Enabled' : 'Disabled'}</span>
      </div>
    );
  }

  return (
    <Input
      id={field.key}
      type={field.type === 'secret' ? 'password' : field.type === 'number' ? 'number' : 'text'}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={field.placeholder ?? undefined}
    />
  );
}

export default ConfigFieldGroup;
