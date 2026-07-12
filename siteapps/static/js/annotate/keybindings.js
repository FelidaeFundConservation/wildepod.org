/*
 * Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */



$(document).ready(function(){
    let imageId = `main-${$('meta[name="django-vars"]').attr('image-id')}`;

    document.onkeydown = function (event) {
        if (event.key === "Backspace" || event.key === "Delete") {
            // Delete annotation keyboard shortcut
            let selected = anno.getSelected();
            let target = null;

            if (selected) {
                target = selected;
            }
            if (hoveredAnnotation) {
                target = hoveredAnnotation;
            }

            if (target && target.type == "Annotation") {
                const annotationText = target.body[0].value && target.body[0].value != 'unannotated' ? target.body[0].value : "(No Annotation)";
                const messageHtml = `<kbd><i class="bi bi-trash"></i>&nbsp;BACKSPACE</kbd>&nbsp;&nbsp;Deleted box '${annotationText}.'</i>`;

                anno.removeAnnotation(target.id);
                anno.cancelSelected();
                userHasDeletedBox = true;
                showBboxWarningMsg();

                appendToast(target.id.replace("#", ""), "delete", messageHtml);
                $(`.tooltip`).remove();

                renderBoundingBoxPreviews("main-{{image.id}}", anno);
            }

            hoveredAnnotation = null;
            selected = null;
        }
        else if (event.key === 'Enter' && event.shiftKey) {
            const messageHtml = `<kbd>SHIFT</kbd> + <kbd>ENTER</kbd>&nbsp;&nbsp;Submitting annotations...</i>`;
            appendToast("shortcut", "submit", messageHtml);
            $('#save_annotations').click();
        }
        else if (event.code === "Space") {
            // Hide all bboxes keyboard shortcut
            event.preventDefault();
            let previews = $(`[class^=preview-]:not(.bbox-hidden):not(.preview-lite)`);
            let messageHtml;

            if (previews.length > 0) {
                previews.addClass("bbox-hidden");
                hiddenBoxes.push(...previews);

                renderBoundingBoxPreviews(imageId, anno);

                messageHtml = `<kbd><i class="bi bi-eye-slash"></i>&nbsp;SPACE</kbd>&nbsp;&nbsp;Hid all visible bounding boxes.</i>`;
                appendToast("id", "hide-all", messageHtml)
            }
            else {
                hiddenBoxes = $(`[class^=preview-]:not(.preview-lite)`);
                reHideBboxes(true);
                messageHtml = `<kbd><i class="bi bi-eye"></i>&nbsp;SPACE</kbd>&nbsp;&nbsp;Unhid all bounding boxes.</i>`;
                appendToast("id", "unhide-all", messageHtml);

                hiddenBoxes = [];
            }
        }

        else if (event.key == 'ArrowLeft') {
            event.preventDefault();
            $(`#context-images-prev`).click();
        }
        else if (event.key == 'ArrowRight') {
            event.preventDefault();
            $(`#context-images-next`).click();
        }

        else if (event.key == 'Enter') {
            $('button.r6o-btn:contains("Ok")').click()
        }
    }
})
