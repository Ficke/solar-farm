import { mount } from "svelte";
import App from "./App.svelte";
import "@fontsource-variable/ibm-plex-sans";
import "uplot/dist/uPlot.min.css";
import "./app.css";

mount(App, { target: document.getElementById("app") as HTMLElement });
