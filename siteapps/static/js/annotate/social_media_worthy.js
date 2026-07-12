/*
 * Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// Handle changing button colors in the UI
function stageSocialMediaWorthyVote(voteType) {
    let upvoteButton = $("#social-media-worthy-up")
    let downvoteButton = $("#social-media-worthy-down")

    if (voteType == "upvote") {
        if (upvoteButton.css("background-color") == "rgb(144, 238, 144)") {
            upvoteButton.css("background-color", "transparent")
        } else {
            upvoteButton.css("background-color", "lightgreen")
            downvoteButton.css("background-color", "transparent")
        }
    }
    else if (voteType == "downvote") {
        if (downvoteButton.css("background-color") == "rgb(255, 204, 203)") {
            downvoteButton.css("background-color", "transparent")
        }
        else {
            downvoteButton.css("background-color", "#FFCCCB")
            upvoteButton.css("background-color", "transparent")
        }
    }
}
