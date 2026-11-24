import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import {
  HEALTH_ALL_GREEN,
  HEALTH_DRIFT_LATCH_ON,
  HEALTH_MODEL_UNREACHABLE,
  HEALTH_NLI_NOT_LOADED,
} from "../fixtures/phase5";
import { HealthPanel } from "./HealthPanel";

const meta = {
  title: "DLE/Admin/HealthPanel",
  component: HealthPanel,
  parameters: {
    dle: { stories: ["US-13"] },
  },
} satisfies Meta<typeof HealthPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AllGreen: Story = {
  args: {
    health: HEALTH_ALL_GREEN,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("All green")).toBeVisible();
    await expect(c.getByText("Reachable")).toBeVisible();
    await expect(c.getByText("Loaded")).toBeVisible();
  },
};

export const ModelUnreachable: Story = {
  args: {
    health: HEALTH_MODEL_UNREACHABLE,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Model unreachable")).toBeVisible();
  },
};

export const NliNotLoaded: Story = {
  args: {
    health: HEALTH_NLI_NOT_LOADED,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("NLI not loaded")).toBeVisible();
  },
};

export const DriftLatchOn: Story = {
  args: {
    health: HEALTH_DRIFT_LATCH_ON,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Drift latch tripped")).toBeVisible();
  },
};
