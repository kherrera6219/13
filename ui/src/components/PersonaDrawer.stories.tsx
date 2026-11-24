import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import {
  OBJECTIONS_CLOSED_VERIFIER,
  OBJECTIONS_OPEN_BLOCKING,
  PERSONAS_ALL_FOUR,
} from "../fixtures/phase4";
import { PersonaDrawer } from "./PersonaDrawer";

const SCHOLAR = PERSONAS_ALL_FOUR[0];
const REGULATOR = PERSONAS_ALL_FOUR[2];

const meta = {
  title: "DLE/Run panel/PersonaDrawer",
  component: PersonaDrawer,
  parameters: {
    dle: { stories: ["US-08"] },
  },
} satisfies Meta<typeof PersonaDrawer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FindingsOnly: Story = {
  args: {
    persona: SCHOLAR,
    objections: [],
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Scholar (Axis 8)")).toBeVisible();
    await expect(c.getByText(/No objections on ledger/i)).toBeVisible();
  },
};

export const OpenBlockingObjection: Story = {
  args: {
    persona: REGULATOR,
    objections: OBJECTIONS_OPEN_BLOCKING,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Blocking")).toBeVisible();
    await expect(c.getByText("Open")).toBeVisible();
    await expect(
      c.getByText("missing_buyer_countersignature_for_change_order"),
    ).toBeVisible();
  },
};

export const ObjectionClosedByVerifier: Story = {
  args: {
    persona: REGULATOR,
    objections: OBJECTIONS_CLOSED_VERIFIER,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Closed by Verifier")).toBeVisible();
    await expect(c.getByText(/claim-buyer-signoff-verified/)).toBeVisible();
  },
};
