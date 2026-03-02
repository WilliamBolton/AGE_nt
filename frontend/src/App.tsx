import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import ConsumerChat from "./pages/ConsumerChat";
import PharmaDashboard from "./pages/PharmaDashboard";
import BiotechDeepDive from "./pages/BiotechDeepDive";
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<ConsumerChat />} />
          <Route path="/pharma" element={<PharmaDashboard />} />
          <Route path="/biotech" element={<BiotechDeepDive />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
