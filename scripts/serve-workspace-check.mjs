/** 实际React交互夹具。所有 /api 请求在页面内隔离，绝不访问正式模型；Ctrl+C退出。 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const requireWeb = createRequire(path.join(root, 'apps/web/package.json'))
const { createServer } = await import(pathToFileURL(requireWeb.resolve('vite')).href)
const data = JSON.parse(fs.readFileSync(path.join(root, '.runtime/qa/discussion/result.json'), 'utf8')).discussion
data.turns = []
data.versions = data.versions.slice(0, 1)
const page = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>工作台交互检查 · 隔离模型</title><div id="qa-badge" style="position:fixed;bottom:0;left:0;z-index:100;font:10px monospace;background:#fff;padding:2px 6px">隔离测试 · 无模型调用 · POST 0</div><div id="root"></div><script type="module">
import React from '/node_modules/.vite-workspace-check/deps/react.js';
import ReactDOM from '/node_modules/.vite-workspace-check/deps/react-dom_client.js';
import {App} from '/src/app/App.tsx';
import '/src/styles/global.css';
const data = ${JSON.stringify(data).replaceAll('<', '\\u003c')};
const report = data.versions[0].report;
const taskId = data.rootTaskId;
let sent = null, started = 0, posts = 0;
const nativeFetch = window.fetch.bind(window);
function job() {
 const elapsed = Date.now() - started;
 const done = sent && elapsed >= 10000;
 if(done && !data.turns.length) data.turns.push({id:'qa-turn', runId:'22222222-2222-4222-8222-222222222222', requestId:sent.requestId, parentTurnId:sent.parentId, baseVersionId:data.versions[0].id, action:sent.action, userMessage:sent.message, status:'completed', answer:'第一段：这是来自隔离服务的真实进度投影。\\n\\n第二段：最终答复已经通过引用校验，原报告没有修改。', citations:[{sourceId:report.sources[0].sourceId,page:report.sources[0].kind==='document'?1:null}], sources:report.sources});
 return {taskId:'22222222-2222-4222-8222-222222222222', target:report.target, status:done?'completed':'running', progress:elapsed<2400?'正在查阅资料':'正在整理回答', phase:'writing', modelCalls:1, usage:{total_tokens:100}, events:[], coverage:[], report:null, error:null, persistence:{unsent:0}, followup:done?{answer:data.turns[0].answer}:elapsed>=2400?{draft:true, answer:elapsed<6000?'第一段：这是来自隔离服务的真实进度投影。':'第一段：这是来自隔离服务的真实进度投影。\\n\\n第二段：还在继续生成，等待最终校验。'}:null};
}
window.fetch = async (input, options={}) => {
 const url = String(input);
 if(!url.startsWith('/api/')) return nativeFetch(input, options);
 let body;
 if(url.endsWith('/chat') && options.method==='POST') {
  sent = JSON.parse(options.body); started = Date.now(); posts++;
  document.querySelector('#qa-badge').textContent='隔离测试 · 无模型调用 · POST '+posts;
  await new Promise(resolve=>setTimeout(resolve,1500));
  body=job();
 } else if(url.endsWith('/discussion')) { if(sent)job(); body=data; }
 else if(url==='/api/research/memory') body={schemaVersion:1,revision:0,enabled:false,notes:[],episodes:[],companies:[],themes:[],companyCount:0,matchedEpisodes:0};
 else if(url.startsWith('/api/research/sessions')) body={sessions:[]};
 else if(url.includes('22222222-2222-4222-8222-222222222222')) body=job();
 else body={taskId, target:report.target, status:'completed',progress:'隔离报告已保存',modelCalls:0,usage:{},events:[],coverage:report.coverage,report,error:null};
 return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
};
history.replaceState(null,'','?task='+taskId);
ReactDOM.createRoot(document.querySelector('#root')).render(React.createElement(App));
</script></html>`
const vite = await createServer({ root: path.join(root, 'apps/web'), cacheDir: path.join(root, 'apps/web/node_modules/.vite-workspace-check'), server: { host: '127.0.0.1', port: 5182, strictPort: true },
  plugins: [{ name: 'isolated-workspace-page', configureServer(server) {
    server.middlewares.use('/__qa', async (_req, res) => {
      res.setHeader('Content-Type', 'text/html;charset=utf-8')
      res.end(await server.transformIndexHtml('/__qa.html', page))
    })
  } }] })
await vite.listen()
console.log(`http://127.0.0.1:5182/__qa · isolated only · pid=${process.pid}`)
