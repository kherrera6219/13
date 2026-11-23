import type { Preview } from "@storybook/react";
import React from "react";
import "../src/tokens.css";

const preview: Preview = {
  globalTypes: {
    theme: {
      description: "DLE color theme",
      defaultValue: "light",
      toolbar: {
        title: "Theme",
        items: [
          { value: "light", title: "Light" },
          { value: "dark", title: "Dark" },
        ],
      },
    },
  },
  decorators: [
    (Story, context) => {
      const theme = context.globals.theme === "dark" ? "dark" : "light";
      if (typeof document !== "undefined") {
        document.documentElement.setAttribute("data-theme", theme);
      }
      return React.createElement(
        "div",
        {
          "data-theme": theme,
          style: {
            backgroundColor: "var(--dle-bg)",
            color: "var(--dle-text)",
            padding: "var(--dle-space-4)",
            minHeight: "100%",
          },
        },
        React.createElement(Story),
      );
    },
  ],
  parameters: {
    a11y: {
      test: "error",
    },
  },
};

export default preview;
