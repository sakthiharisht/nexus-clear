import { NavLink, Route, Routes } from "react-router-dom";
import CaseHome from "./pages/CaseHome";
import FindingsReport from "./pages/FindingsReport";
import ReviewerQueue from "./pages/ReviewerQueue";
import PacketAttest from "./pages/PacketAttest";
import EvalDashboard from "./pages/EvalDashboard";

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title">Credentialing Readiness Agent</div>
        <nav className="app-nav">
          <NavLink to="/" end>
            Case
          </NavLink>
          <NavLink to="/report">Findings</NavLink>
          <NavLink to="/reviews">Reviewer queue</NavLink>
          <NavLink to="/packet">Packet &amp; attest</NavLink>
          <NavLink to="/eval">Eval dashboard</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<CaseHome />} />
          <Route path="/report" element={<FindingsReport />} />
          <Route path="/reviews" element={<ReviewerQueue />} />
          <Route path="/packet" element={<PacketAttest />} />
          <Route path="/eval" element={<EvalDashboard />} />
        </Routes>
      </main>
      <footer className="app-footer">
        Synthetic data only. Never submits to a payer or writes to CAQH/DataSpring.
      </footer>
    </div>
  );
}

export default App;
