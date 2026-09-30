"use client";

import type { ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Checkbox } from "@/components/ui/Checkbox";
import { FieldError } from "@/components/ui/Field";
import { ChevronDownIcon } from "@/components/ui/icons";

// The scout form's choice lists (docs/spec/06 6.8 "form, not prompt-writing"): niches by parent, counties in a
// disclosure (47 of them), how far along, and the digest's reviewer seats. Each is a fieldset of full-row checkboxes.

export interface NicheOption {
  id: string;
  name: string;
  children: { id: string; name: string }[];
}

export interface Option {
  id: string;
  label: string;
}

/** Adds or removes one value, keeping the list's order of choice. */
export function toggle<T>(list: readonly T[], value: T, on: boolean): T[] {
  return on ? (list.includes(value) ? [...list] : [...list, value]) : list.filter((v) => v !== value);
}

function Group({
  id,
  legend,
  hint,
  error,
  children,
}: {
  id: string;
  legend: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  const described = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return (
    <fieldset id={id} aria-describedby={described} className="flex min-w-0 flex-col" tabIndex={-1}>
      <legend className="font-medium text-ink">{legend}</legend>
      {hint ? (
        <p id={`${id}-hint`} className="mt-1 text-sm text-ink-soft">
          {hint}
        </p>
      ) : null}
      {error ? (
        <div className="mt-1.5">
          <FieldError id={`${id}-error`}>{error}</FieldError>
        </div>
      ) : null}
      <div className="mt-1">{children}</div>
    </fieldset>
  );
}

/** Niches grouped under their parent; choosing a parent also covers the niches under it (the API's rule). */
export function NicheChoice(props: {
  id: string;
  niches: NicheOption[];
  chosen: string[];
  error?: string;
  max: number;
  onChange: (next: string[]) => void;
}) {
  const t = useStrings("scoutForm");
  return (
    <Group id={props.id} legend={t("niches")} hint={t("nichesHint", { max: props.max })} error={props.error}>
      <ul className="gap-x-8 sm:columns-2">
        {props.niches.map((parent) => (
          <li key={parent.id} className="min-w-0 break-inside-avoid">
            <Checkbox
              id={`${props.id}-${parent.id}`}
              label={<span className="font-semibold">{parent.name}</span>}
              checked={props.chosen.includes(parent.id)}
              onChange={(e) => props.onChange(toggle(props.chosen, parent.id, e.target.checked))}
            />
            {parent.children.length > 0 ? (
              <ul className="ml-8">
                {parent.children.map((child) => (
                  <li key={child.id}>
                    <Checkbox
                      id={`${props.id}-${child.id}`}
                      label={child.name}
                      checked={props.chosen.includes(child.id)}
                      onChange={(e) => props.onChange(toggle(props.chosen, child.id, e.target.checked))}
                    />
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </Group>
  );
}

/** Counties in a disclosure that says how many are chosen; none chosen is all of Kenya. */
export function CountyChoice(props: {
  id: string;
  counties: Option[];
  chosen: string[];
  onChange: (next: string[]) => void;
}) {
  const t = useStrings("scoutForm");
  const count = props.chosen.length;
  return (
    <Group id={props.id} legend={t("counties")} hint={t("countiesHint")}>
      <details className="group" open={count > 0 ? true : undefined}>
        <summary
          className={
            "inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 font-semibold text-jacaranda " +
            "[&::-webkit-details-marker]:hidden"
          }
        >
          <ChevronDownIcon className="size-5 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
          {count > 0 ? t("countiesChosen", { count }) : t("countiesAny")}
        </summary>
        <ul className="grid grid-cols-1 gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
          {props.counties.map((county) => (
            <li key={county.id}>
              <Checkbox
                id={`${props.id}-${county.id}`}
                label={county.label}
                checked={props.chosen.includes(county.id)}
                onChange={(e) => props.onChange(toggle(props.chosen, county.id, e.target.checked))}
              />
            </li>
          ))}
        </ul>
      </details>
    </Group>
  );
}

/** A plain list of checkboxes (how far along; the digest's reviewers). */
export function ChoiceList(props: {
  id: string;
  legend: string;
  hint?: string;
  options: Option[];
  chosen: string[];
  columns?: boolean;
  onChange: (next: string[]) => void;
}) {
  return (
    <Group id={props.id} legend={props.legend} hint={props.hint}>
      <ul className={props.columns ? "grid grid-cols-2 gap-x-6 sm:grid-cols-4" : "flex flex-col"}>
        {props.options.map((option) => (
          <li key={option.id}>
            <Checkbox
              id={`${props.id}-${option.id}`}
              label={option.label}
              checked={props.chosen.includes(option.id)}
              onChange={(e) => props.onChange(toggle(props.chosen, option.id, e.target.checked))}
            />
          </li>
        ))}
      </ul>
    </Group>
  );
}
