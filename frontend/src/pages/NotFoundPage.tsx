import { Link } from "react-router";
import { Compass } from "lucide-react";
import { EmptyState } from "../components/Feedback";

export function NotFoundPage() {
  return (
    <div className="card">
      <EmptyState
        icon={<Compass size={20} />}
        title="Page not found"
        action={
          <Link to="/campaigns" className="btn btn--primary">
            Back to campaigns
          </Link>
        }
      >
        The page you were looking for doesn't exist or has moved.
      </EmptyState>
    </div>
  );
}
