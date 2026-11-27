import { createApp } from "vue";
import App from "./App.vue";
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import * as lucide from 'lucide';
import renderMathInElement from 'katex/contrib/auto-render';
import 'katex/dist/katex.min.css';
import '../../web/colors_and_type.css';
import '../../web/styles.css';
import './platform.css';

Object.assign(window, { marked, DOMPurify, lucide: { createIcons: () => lucide.createIcons({ icons: lucide.icons }) }, renderMathInElement });

createApp(App).mount("#app");
