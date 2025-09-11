import React from "react";
import SubredditCard from "./SubredditCard";

interface SubredditResult {
  subreddit: string;
  score?: number;
  description?: string;
  rules?: string[];
  ai_warning?: string[];
  subscribers?: number;
}

interface RedditUser {
  name: string;
  icon_img?: string;
}

interface SubredditResultsListProps {
  resultsWithTestSub: SubredditResult[];
  abbreviateNumber: (value: number) => string;
  title: string;
  body: string;
  link: string;
  postType: "text" | "media" | "link";
  postingSub: string | null;
  setPostingSub: (v: string | null) => void;
  postTitle: string;
  setPostTitle: (v: string) => void;
  postBody: string;
  setPostBody: (v: string) => void;
  postError: string;
  setPostError: (v: string) => void;
  postLoading: boolean;
  handleSubmitToReddit: (e: React.FormEvent) => void;
  postConfirmations: { [sub: string]: string };
  postFiles: File[];
  handleClearFiles: () => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  sentinelRef: React.RefObject<HTMLDivElement>;
  loading: boolean;
  hasMore: boolean;
  onRequestPostToSubreddit: (subreddit: string) => void;
  user: RedditUser | null;
}

// New handler wrapper to inject flair/tags from window into FormData
function withFlairAndTags(
  handleSubmit: (e: React.FormEvent) => void
): (e: React.FormEvent) => void {
  return (e: React.FormEvent) => {
    // Add flair/tags to FormData using window globals (set in SubredditCard)
    const flair_id = (window as any).__selectedFlair || "";
    const tags = (window as any).__selectedTags || {};
    // Attach to form fields (if present)
    const form = e.target as HTMLFormElement;
    if (form) {
      // Find or create hidden inputs for flair and tags
      let flairInput = form.querySelector("input[name='flair_id']") as HTMLInputElement;
      if (!flairInput) {
        flairInput = document.createElement("input");
        flairInput.type = "hidden";
        flairInput.name = "flair_id";
        form.appendChild(flairInput);
      }
      flairInput.value = flair_id || "";
      let nsfwInput = form.querySelector("input[name='nsfw']") as HTMLInputElement;
      if (!nsfwInput) {
        nsfwInput = document.createElement("input");
        nsfwInput.type = "hidden";
        nsfwInput.name = "nsfw";
        form.appendChild(nsfwInput);
      }
      nsfwInput.value = tags.nsfw ? "true" : "";
      let brandInput = form.querySelector("input[name='brand_affiliate']") as HTMLInputElement;
      if (!brandInput) {
        brandInput = document.createElement("input");
        brandInput.type = "hidden";
        brandInput.name = "brand_affiliate";
        form.appendChild(brandInput);
      }
      brandInput.value = tags.brand ? "true" : "";
    }
    handleSubmit(e);
  };
}

const SubredditResultsList: React.FC<SubredditResultsListProps> = ({
  resultsWithTestSub,
  abbreviateNumber,
  title,
  body,
  link,
  postType,
  postingSub,
  setPostingSub,
  postTitle,
  setPostTitle,
  postBody,
  setPostBody,
  postError,
  setPostError,
  postLoading,
  handleSubmitToReddit,
  postConfirmations,
  postFiles,
  handleClearFiles,
  fileInputRef,
  sentinelRef,
  loading,
  hasMore,
  onRequestPostToSubreddit,
  user,
}) => (
  <div className="space-y-4">
    {resultsWithTestSub.map((sub, idx) => (
      <SubredditCard
        key={sub.subreddit || idx}
        sub={sub}
        abbreviateNumber={abbreviateNumber}
        title={title}
        body={body}
        link={link}
        postType={postType}
        postingSub={postingSub}
        setPostingSub={setPostingSub}
        postTitle={postTitle}
        setPostTitle={setPostTitle}
        postBody={postBody}
        setPostBody={setPostBody}
        postError={postError}
        setPostError={setPostError}
        postLoading={postLoading}
        // Wrap submit handler to add flair/tag values
        handleSubmitToReddit={withFlairAndTags(handleSubmitToReddit)}
        postConfirmations={postConfirmations}
        postFiles={postFiles}
        handleClearFiles={handleClearFiles}
        fileInputRef={fileInputRef}
        onRequestPostToSubreddit={onRequestPostToSubreddit}
        user={user}
      />
    ))}
    <div ref={sentinelRef} style={{ height: 48, width: "100%" }} className="flex items-center justify-center">
      {loading && <span className="text-gray-400 text-sm">Loading subreddits...</span>}
    </div>
  </div>
);

export default SubredditResultsList;
