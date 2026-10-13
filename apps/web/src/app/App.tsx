import { ResearchWorkspace } from '../features/research-lab/ResearchWorkspace'

export function App() {
  return (
    <>
      <a className="skip-link" href="#research-target">跳到研究输入</a>
      <header className="site-header" id="top">
        <a className="brand" href="#top" aria-label="市场之路首页">
          <span className="brand-mark" aria-hidden="true">PM</span>
          <span className="brand-name">Path of Market <span>市场之路</span></span>
        </a>
        <nav aria-label="主导航">
          <a className="nav-current" href="#research-workspace" aria-current="page">深研室</a>
        </nav>
        <span className="header-caption">个人财经研究工作台</span>
      </header>
      <main id="research-workspace">
        <ResearchWorkspace />
      </main>
      <footer className="site-footer">
        <span>PATH OF MARKET <span className="footer-divider">/</span> 从问题开始，逐步积累。</span>
        <a href="#top">返回顶部 ↑</a>
      </footer>
    </>
  )
}
