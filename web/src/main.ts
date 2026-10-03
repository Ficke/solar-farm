import { mount } from "svelte";
import App from "./App.svelte";
import "uplot/dist/uPlot.min.css";
import "./app.css";

mount(App, { target: document.getElementById("app") as HTMLElement });
