import { BrowserRouter, Route, Routes } from "react-router-dom";
import Landing from "./pages/Landing";
import RunView from "./pages/RunView";
import NoteView from "./pages/NoteView";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/run/:runId" element={<RunView />} />
        <Route path="/run/:runId/note" element={<NoteView />} />
      </Routes>
    </BrowserRouter>
  );
}
