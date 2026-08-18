.text
.global _start
.extern run_command
.extern install_script
.extern post_script
.extern epilogue
_start:
    adrp x0, install_script
    add  x0, x0, :lo12:install_script
    mov  w1, #0
    bl   run_command
    cbnz w0, fail
    adrp x0, post_script
    add  x0, x0, :lo12:post_script
    mov  w1, #0
    bl   run_command
    cbz  w0, epilogue
fail:
    mov  w0, #-1
    b    epilogue
