import "./assets/main.css";

import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";

import { createPinia } from "pinia";
import piniaPluginPersistedstate from "pinia-plugin-persistedstate";
import ElButton from "element-plus/es/components/button/index.mjs";
import ElCard from "element-plus/es/components/card/index.mjs";
import ElCascader from "element-plus/es/components/cascader/index.mjs";
import ElEmpty from "element-plus/es/components/empty/index.mjs";
import ElSelect, {
  ElOption,
} from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/base/style/css";
import "element-plus/es/components/button/style/css";
import "element-plus/es/components/card/style/css";
import "element-plus/es/components/cascader/style/css";
import "element-plus/es/components/empty/style/css";
import "element-plus/es/components/option/style/css";
import "element-plus/es/components/select/style/css";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/notification/style/css";

const app = createApp(App);

const pinia = createPinia();
pinia.use(piniaPluginPersistedstate);

app.use(pinia);
app.use(router);
app.use(ElButton);
app.use(ElCard);
app.use(ElCascader);
app.use(ElEmpty);
app.use(ElOption);
app.use(ElSelect);

app.mount("#app");
