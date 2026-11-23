import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import {
  SAMPLE_COORDINATE,
  SAMPLE_DENSE_ONLY_GRAPH,
  SAMPLE_GRAPH,
} from "../fixtures/phase3";
import { AddressGraphDrawer } from "./AddressGraphDrawer";

const meta = {
  title: "DLE/Run panel/AddressGraphDrawer",
  component: AddressGraphDrawer,
  parameters: {
    dle: { stories: ["US-06", "US-08"] },
  },
} satisfies Meta<typeof AddressGraphDrawer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WarehousePilot: Story = {
  args: {
    coordinate: SAMPLE_COORDINATE,
    graph: SAMPLE_GRAPH,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("PPR active")).toBeVisible();
    await expect(c.getByText("[NODE:5.42]")).toBeVisible();
    await expect(c.getByText("Hypothesis only")).toBeVisible();
    await userEvent.click(c.getByText(/Traversed Spine Edges/i));
    await expect(c.getByText(/honeycomb_link/)).toBeVisible();
  },
};

export const DenseOnlyPprOff: Story = {
  args: {
    coordinate: SAMPLE_COORDINATE,
    graph: SAMPLE_DENSE_ONLY_GRAPH,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Dense retrieval only")).toBeVisible();
  },
};

export const Empty: Story = {
  args: {
    coordinate: null,
    graph: null,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/Send a governed query/i)).toBeVisible();
  },
};
