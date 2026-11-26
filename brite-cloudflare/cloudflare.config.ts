import { bindings, defineConfig, triggers } from "cf/config";
export default defineConfig({worker:{
  name:"brite-redteam-api",entrypoint:"./src/entry.py",compatibilityDate:"2026-11-26",compatibilityFlags:["python_workers"],
  env:{DB:bindings.d1({name:"brite-redteam-db"}),OPENAI_API_KEY:bindings.secret(),ANTHROPIC_API_KEY:bindings.secret(),APP_ORIGIN:bindings.secret()},
  access:{dev:{aud:"brite-redteam-local",identity:{email:"admin@example.org"}}},
  triggers:[triggers.scheduled({schedule:"*/15 * * * *"})]
}});
