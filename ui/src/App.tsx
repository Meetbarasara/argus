import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Approvals from "./pages/Approvals";
import Dashboard from "./pages/Dashboard";
import IncidentDetail from "./pages/IncidentDetail";
import Incidents from "./pages/Incidents";
import Memory from "./pages/Memory";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Incidents />} />
        <Route path="/incidents/:id" element={<IncidentDetail />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="/dashboard" element={<Dashboard />} />
      </Routes>
    </Layout>
  );
}
