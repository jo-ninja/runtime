// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.

using System.Collections.Generic;

namespace System.Diagnostics
{
    /// <summary>
    /// Define the callback that can be used in <see cref="ActivityListener"/> to allow deciding to create the Activity objects and with what data state.
    /// </summary>
    public delegate ActivityDataRequest GetRequestedData<T>(ref ActivityCreationOptions<T> options);

    /// <summary>
    /// ActivityListener allows listening to the start and stop Activity events and give the oppertunity to decide creating the Activity for sampling scenarios.
    /// </summary>
    public sealed class ActivityListener : IDisposable
    {
        /// <summary>
        /// Construct a new <see cref="ActivityListener"/> object to start listeneing to the <see cref="Activity"/> events.
        /// </summary>
        public ActivityListener()
        {
        }

        /// <summary>
        /// Set or get the callback used to listen to the <see cref="Activity"/> start event.
        /// </summary>
        public Action<Activity>? ActivityStarted { get; set; }

        /// <summary>
        /// Set or get the callback used to listen to the <see cref="Activity"/> stop event.
        /// </summary>
        public Action<Activity>? ActivityStopped { get; set; }

        /// <summary>
        /// Set or get the callback used to decide if want to listen to <see cref="Activity"/> objects events which created using <see cref="ActivitySource"/> object.
        /// </summary>
        public Func<ActivitySource, bool>? ShouldListenTo { get; set; }

        /// <summary>
        /// Set or get the callback used to decide allowing creating <see cref="Activity"/> objects with specific data state.
        /// </summary>
        public GetRequestedData<string>? GetRequestedDataUsingParentId { get; set; }

        /// <summary>
        /// Set or get the callback used to decide allowing creating <see cref="Activity"/> objects with specific data state.
        /// </summary>
        public GetRequestedData<ActivityContext>? GetRequestedDataUsingContext { get; set; }

        /// <summary>
        /// Determine if the listener automatically generates a new trace Id before sampling when there is no parent context.
        /// </summary>
        /// <remarks>
        /// If this property is set to true and caused generating a new trace Id, the created <see cref="Activity"/> object from such call will have the same generated trace Id.
        /// </remarks>
        public bool AutoGenerateRootContextTraceId { get; set;}

        /// <summary>
        /// Dispose will unregister this <see cref="ActivityListener"/> object from listeneing to <see cref="Activity"/> events.
        /// </summary>
        public void Dispose() => ActivitySource.DetachListener(this);
   }
}
